"""Fusion agent — turns the gathered evidence into the answer.

Runs after the three evidence pathways report and before the consistency audit,
on every round:

    propose -> three pathways -> FUSION -> audit -> (revise -> ...)

Fusion and the audit answer different questions, which is why they are separate
calls. Fusion asks "given everything retrieved, what is the ranking?" and its
output is the differential the caller receives. The audit asks "has this
settled?" and its output is a verdict plus, when the answer is no, the findings
to revise against.

Without this step the differential is whatever the proposing model last said, and
a case the audit passes on the first round returns the initial proposal unchanged
— with three pathways' worth of evidence gathered and never applied.

The case text is the primary source here. Retrieved evidence is secondary: it is
condensed, paraphrased, and sometimes about a different patient. Where the two
disagree, the case wins.
"""
from __future__ import annotations

import json

from ..llm.base import ChatModel, parse_json
from ..prompts import EVIDENCE_FUSION
from ..types import Candidate, Evidence, FusionResult, Phenotype, Reference


async def run(model: ChatModel, text: str, phenotypes: list[Phenotype],
              candidates: list[Candidate], evidence: list[Evidence],
              proposed: list[Candidate] | None = None,
              k: int = 5, max_tokens: int = 8192) -> FusionResult:
    """Rank the differential against the evidence, and say whether to reflect.

    Raises on an unusable reply rather than quietly returning the input
    differential — an unfused answer looks like a normal one, so a batch run
    would record it as a result.
    """
    by_cand: dict[str, list[Evidence]] = {}
    for ev in evidence:
        by_cand.setdefault(ev.candidate_key, []).append(ev)

    # Evidence is numbered so the model can cite it, and so the citations in the
    # answer can be checked against what was actually retrieved.
    numbered: list[tuple[str, Evidence]] = []
    for i, ev in enumerate(evidence, start=1):
        numbered.append((f"[{i}]", ev))
    marker_of = {id(ev): m for m, ev in numbered}

    user = json.dumps({
        "clinical_case": text,
        "findings_present": [p.name for p in phenotypes if p.present],
        "findings_absent": [p.name for p in phenotypes if not p.present],
        "working_differential": [
            {
                "rank": c.rank,
                "name": c.name,
                "rationale": c.rationale,
                "supporting_findings": c.supporting_findings,
                "contradictory_findings": c.contradictory_findings,
                "unresolved_questions": c.unresolved_questions,
                "evidence": [
                    {"citation": marker_of[id(e)], "pathway": e.kind.value,
                     "stance": e.stance.value, "source": e.source,
                     "record": e.text()}
                    for e in by_cand.get(c.key(), [])
                ],
            }
            for c in sorted(candidates, key=lambda c: c.rank)
        ],
        "alternatives_proposed_by_agents": [
            {"name": c.name, "rationale": c.rationale} for c in (proposed or [])
        ],
        "candidates_requested": k,
    }, ensure_ascii=False, default=str)

    raw = await model.chat(EVIDENCE_FUSION, user, temperature=0.2,
                           max_tokens=max_tokens)
    obj = parse_json(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"fusion reply was not a JSON object ({len(raw)} chars)")
    items = obj.get("q1_diagnoses") or obj.get("candidates") or []
    if not isinstance(items, list) or not items:
        raise ValueError("fusion reply carried no candidates")

    # Carry forward what earlier stages wrote, so a fusion reply that reorders
    # without restating the findings does not erase them.
    #
    # Matched on the ontology key first, then on any of the names a candidate is
    # known by. The prompt invites fusion to give 2-3 synonyms joined by " / ",
    # so an exact-name lookup misses on exactly the replies it should match — and
    # a miss loses the findings, the concept ids, and with them the evidence
    # already gathered under the old key.
    prior: dict[str, Candidate] = {}
    for c in list(candidates) + list(proposed or []):
        prior[c.key()] = c
        for alias in _aliases(c.name):
            prior.setdefault(alias, c)

    out: list[Candidate] = []
    for i, item in enumerate(items[:k], start=1):
        if isinstance(item, str):
            name, item = item.strip(), {}
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("diagnosis") or "").strip()
        else:
            continue
        if not name:
            continue
        old = None
        for alias in _aliases(name):
            old = prior.get(alias)
            if old is not None:
                break
        out.append(Candidate(
            name=name,
            rank=i,
            rationale=str(item.get("reasoning") or item.get("rationale") or "")
                      or (old.rationale if old else ""),
            rarity=str(item.get("rarity") or ""),
            confidence=str(item.get("confidence") or ""),
            exams=str(item.get("exams") or ""),
            supporting_findings=list(old.supporting_findings) if old else [],
            contradictory_findings=list(old.contradictory_findings) if old else [],
            unresolved_questions=list(old.unresolved_questions) if old else [],
            concept_ids=dict(old.concept_ids) if old else {},
        ))

    refs: list[Reference] = []
    for r in (obj.get("references") or []):
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        refs.append(Reference(id=rid, type=str(r.get("type") or ""),
                              description=str(r.get("description") or ""),
                              source=str(r.get("source") or "")))

    if not out:
        raise ValueError("no candidate in the fusion reply had a usable name")

    return FusionResult(
        candidates=out,
        references=refs,
        reflection_needed=bool(obj.get("reflection_needed")),
        reflection_reason=str(obj.get("reflection_reason") or ""),
    )


def _aliases(name: str) -> list[str]:
    """Lookup keys for a candidate name: the whole string, then each synonym.

    `"MELAS syndrome / 线粒体脑肌病"` yields the full string plus each side, so a
    fusion reply that adds or drops a synonym still resolves to the candidate the
    evidence was gathered for.
    """
    whole = name.strip().casefold()
    out = [whole]
    for part in name.split("/"):
        part = part.strip().casefold()
        if part and part != whole:
            out.append(part)
    return out
