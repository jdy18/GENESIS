"""The reasoning engine — the model that proposes and revises the differential.

Two entry points: an initial pass producing K candidate diagnoses, and a revision
pass that reworks them given the audit report.

Both return the same record shape, because the evidence agents cannot tell — and
must not care — which pass produced the candidates they are examining.
"""
from __future__ import annotations

import json

from .llm.base import ChatModel, parse_json
from .prompts import INITIAL_DIFFERENTIAL, REVISED_DIFFERENTIAL
from .types import AuditReport, Candidate, Evidence, Phenotype


async def propose(
    model: ChatModel,
    text: str,
    phenotypes: list[Phenotype],
    k: int = 5,
    max_tokens: int = 4096,
) -> list[Candidate]:
    """Initial differential — the single-model baseline.

    Sees the case and the extracted findings, nothing else, so what it returns is
    the floor the rest of the workflow has to beat.
    """
    user = json.dumps(
        {
            "clinical_text": text,
            "findings_present": [p.name for p in phenotypes if p.present],
            "findings_absent": [p.name for p in phenotypes if not p.present],
            "candidates_requested": k,
        },
        ensure_ascii=False,
    )
    raw = await model.chat(
        INITIAL_DIFFERENTIAL, user, temperature=0.3, max_tokens=max_tokens
    )
    return _parse(raw, k)


async def revise(
    model: ChatModel,
    text: str,
    phenotypes: list[Phenotype],
    previous: list[Candidate],
    report: AuditReport,
    evidence: list[Evidence] | None = None,
    k: int = 5,
    max_tokens: int = 4096,
) -> list[Candidate]:
    """Revised differential: the same case, plus everything the agents gathered.

    This is the step where the model that proposed the differential gets to see
    what the evidence pathways found. It receives the retrieved records
    themselves, not only the audit's account of them — the audit names what is
    missing, while the records are what a new candidate would be reasoned from.
    """
    by_cand: dict[str, list[Evidence]] = {}
    for ev in evidence or []:
        by_cand.setdefault(ev.candidate_key, []).append(ev)

    user = json.dumps(
        {
            "clinical_text": text,
            "findings_present": [p.name for p in phenotypes if p.present],
            "findings_absent": [p.name for p in phenotypes if not p.present],
            "previous_differential": [
                {
                    "rank": c.rank,
                    "name": c.name,
                    "rationale": c.rationale,
                    "supporting_findings": c.supporting_findings,
                    "contradictory_findings": c.contradictory_findings,
                    "unresolved_questions": c.unresolved_questions,
                    "evidence": [
                        {
                            "pathway": e.kind.value,
                            "stance": e.stance.value,
                            "source": e.source,
                            "record": e.text(),
                        }
                        for e in by_cand.get(c.key(), [])
                    ],
                }
                for c in sorted(previous, key=lambda c: c.rank)
            ],
            "audit_report": {
                "unsupported_claims": report.unsupported_claims,
                "conflicting_findings": report.conflicting_findings,
                "evidence_gaps": report.evidence_gaps,
                "alternatives_proposed": [
                    {"name": c.name, "rationale": c.rationale}
                    for c in report.proposed_alternatives
                ],
                "assessment": report.reasoning,
            },
            "candidates_requested": k,
        },
        ensure_ascii=False,
    )
    raw = await model.chat(
        REVISED_DIFFERENTIAL, user, temperature=0.3, max_tokens=max_tokens
    )
    revised = _parse(raw, k)
    # A revision that returns nothing usable must not erase the differential —
    # returning [] here would score as a non-answer even though the previous
    # cycle had a perfectly good ranking.
    return revised or previous


def _parse(raw: str, k: int) -> list[Candidate]:
    obj = parse_json(raw)
    items = (obj.get("candidates") if isinstance(obj, dict) else obj) or []
    if not isinstance(items, list):
        return []
    out: list[Candidate] = []
    for i, item in enumerate(items[:k], start=1):
        if isinstance(item, str):
            out.append(Candidate(name=item.strip(), rank=i))
            continue
        if not isinstance(item, dict):
            continue
        name = str(
            item.get("name")
            or item.get("diagnosis_name")
            or item.get("diagnosis")
            or ""
        ).strip()
        if not name:
            continue
        try:
            rank = int(item.get("rank", i))
        except (TypeError, ValueError):
            rank = i
        out.append(
            Candidate(
                name=name,
                rank=rank,
                supporting_findings=_strs(item.get("supporting_findings")),
                contradictory_findings=_strs(item.get("contradictory_findings")),
                unresolved_questions=_strs(item.get("unresolved_questions")),
                rationale=str(item.get("rationale") or item.get("reasoning") or ""),
            )
        )
    # Renumber: models skip and repeat ranks, and downstream agreement scoring
    # assumes 1..n dense.
    for i, c in enumerate(sorted(out, key=lambda c: c.rank), start=1):
        c.rank = i
    return sorted(out, key=lambda c: c.rank)


def _strs(v: object) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []
