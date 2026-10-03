"""Historical-case analogy agent.

Asks whether the index case resembles previously documented presentations.

Three representations go to each index — a phenotype term set, the free-text
narrative, and the candidate disease names — and the index uses whichever it
supports.

The auxiliary model compares each retrieved case’s reported diagnosis with a
candidate diagnosis. GENESIS-R1 compares the current patient’s findings and
disease course with the historical cases, explains evidence for or against the
candidates and may suggest other diagnoses documented in those cases. Original
records and their sources remain attached to the report.
"""
from __future__ import annotations

import asyncio
import json

from ..llm.base import ChatModel, parse_json
from ..prompts import ANALOGY_SAME_ENTITY, ANALOGY_SYNTHESIS
from ..tools.base import CaseIndex
from ..types import (
    AgentReport,
    Candidate,
    Evidence,
    EvidenceKind,
    Phenotype,
    Stance,
)


async def run(
    candidates: list[Candidate],
    phenotypes: list[Phenotype],
    text: str,
    indices: list[CaseIndex],
    model: ChatModel,
    top_k: int = 3,
    auxiliary: ChatModel | None = None,
) -> AgentReport:
    """Retrieve cases, match reported diagnoses to candidates, then compare cases.

    `model` supplies GENESIS-R1. Without a separate auxiliary model, it also runs
    the same-entity checks. One synthesis call evaluates all retrieved cases.
    """
    if not indices:
        return AgentReport(
            kind=EvidenceKind.ANALOGY, notes="no case indices configured"
        )

    names = [c.name for c in candidates]
    fetched = await asyncio.gather(
        *[ix.search(phenotypes, text, names, top_k) for ix in indices],
        return_exceptions=True,
    )

    records, failures = [], []
    for ix, res in zip(indices, fetched):
        if isinstance(res, BaseException):
            failures.append(f"{ix.name}: {type(res).__name__}")
            continue
        for n, rec in enumerate(res or [], 1):
            if not isinstance(rec, dict):
                continue
            source_id = next((rec[k] for k in ("case_id", "id", "pmid")
                              if rec.get(k) not in (None, "")), None)
            label = (f"case {source_id}" if source_id is not None
                     else str(rec.get("title") or f"retrieved result {n}"))
            records.append((f"{ix.name} — {label}",
                            str(source_id) if source_id is not None else None, rec))

    if not records:
        return AgentReport(
            kind=EvidenceKind.ANALOGY,
            failed=bool(failures) and not records,
            error="; ".join(failures) or None,
            evidence=[
                Evidence(
                    candidate_key=c.key(),
                    kind=EvidenceKind.ANALOGY,
                    stance=Stance.NEUTRAL,
                    content="No analogous cases retrieved.",
                    source="case analogy (empty)",
                )
                for c in candidates
            ],
        )

    # Verdict per (candidate, record). Bounded so a large top_k across several
    # indices cannot fan out into thousands of calls.
    pairs = [(c, source, sid, rec) for c in candidates
             for source, sid, rec in records][:200]
    verdicts = await asyncio.gather(
        *[_verdict(auxiliary or model, c, rec, text) for c, _, _, rec in pairs],
        return_exceptions=True,
    )

    checks = []
    matched = []
    for (cand, source, sid, rec), v in zip(pairs, verdicts):
        if not isinstance(v, dict) or not isinstance(v.get("same_entity"), bool):
            failures.append(f"same-entity check unavailable: {cand.name}; {source}")
            continue
        checks.append({"candidate": cand.name, "source": source,
                       "same_entity": v["same_entity"],
                       "justification": str(v.get("justification", ""))})
        if v["same_entity"]:
            matched.append((cand, source, sid, rec))

    user = json.dumps({
        "clinical_case": text,
        "findings_present": [p.name for p in phenotypes if p.present],
        "findings_absent": [p.name for p in phenotypes if not p.present],
        "working_differential": [{
            "name": c.name, "rank": c.rank, "rationale": c.rationale,
            "supporting_findings": c.supporting_findings,
            "contradictory_findings": c.contradictory_findings,
            "unresolved_questions": c.unresolved_questions,
        } for c in sorted(candidates, key=lambda c: c.rank)],
        "retrieved_cases": [{"source": source, "source_id": sid, "record": rec}
                            for source, sid, rec in records],
        "same_entity_checks": checks,
    }, ensure_ascii=False, default=str)

    synthesis = None
    try:
        reply = parse_json(await model.chat(
            ANALOGY_SYNTHESIS, user, temperature=0.2, max_tokens=4096))
        if not isinstance(reply, dict) or not all(
            isinstance(reply.get(k), list) for k in ("assessments", "alternatives")
        ):
            raise ValueError("analogy synthesis must contain assessments and alternatives lists")
        synthesis = reply
    except Exception as exc:
        failures.append(f"synthesis: {type(exc).__name__}; retained original matched records")

    evidence: list[Evidence] = []
    alternatives: list[Candidate] = []
    by_source = {source: (sid, rec) for source, sid, rec in records}
    by_name = {c.name.strip().casefold(): c for c in candidates}
    attached = set()

    def attach(cand: Candidate, item: dict, stance: Stance, summary: str) -> None:
        for source in item["sources"]:
            pair = (cand.key(), source)
            if pair in attached:
                continue
            sid, rec = by_source[source]
            evidence.append(_evidence(cand, source, sid, rec, stance, summary))
            attached.add(pair)

    for item in (synthesis or {}).get("assessments", []):
        if not _valid_sources(item, by_source):
            failures.append("synthesis assessment omitted: missing or unknown source")
            continue
        cand = by_name.get(str(item.get("candidate", "")).strip().casefold())
        try:
            stance = Stance(item.get("stance"))
        except (ValueError, TypeError):
            continue
        if cand and isinstance(item.get("summary"), str) and item["summary"].strip():
            attach(cand, item, stance, item["summary"])

    for item in (synthesis or {}).get("alternatives", []):
        if not _valid_sources(item, by_source):
            failures.append("synthesis alternative omitted: missing or unknown source")
            continue
        name, rationale = item.get("name"), item.get("rationale")
        if (not isinstance(name, str) or not name.strip()
                or not isinstance(rationale, str) or not rationale.strip()):
            continue
        if name.strip().casefold() in by_name or len(alternatives) >= 5:
            continue
        cand = Candidate(name=name.strip(), rank=len(alternatives) + 1, rationale=rationale)
        alternatives.append(cand)
        by_name[name.strip().casefold()] = cand
        attach(cand, item, Stance.SUPPORTS, rationale)

    # An identity match alone carries no clinical stance. Preserve its source
    # when synthesis fails or omits the pair, without claiming diagnostic support.
    for cand, source, sid, rec in matched:
        if (cand.key(), source) not in attached:
            evidence.append(_evidence(cand, source, sid, rec, Stance.NEUTRAL, ""))
            attached.add((cand.key(), source))

    covered = {e.candidate_key for e in evidence}
    for cand in candidates:
        if cand.key() not in covered:
            evidence.append(
                Evidence(
                    candidate_key=cand.key(),
                    kind=EvidenceKind.ANALOGY,
                    stance=Stance.NEUTRAL,
                    content=(
                        "No source-backed case-analogy assessment is available for this candidate."
                    ),
                    source="case analogy (no match)",
                )
            )

    return AgentReport(
        kind=EvidenceKind.ANALOGY,
        evidence=evidence,
        new_candidates=alternatives,
        notes="; ".join(failures),
        synthesis=synthesis,
    )


def _valid_sources(item: object, available: dict) -> bool:
    if not isinstance(item, dict):
        return False
    sources = item.get("sources")
    return (isinstance(sources, list) and bool(sources)
            and all(isinstance(s, str) and s in available for s in sources))


def _evidence(cand: Candidate, source: str, sid: str | None, rec: dict,
              stance: Stance, summary: str) -> Evidence:
    return Evidence(
        candidate_key=cand.key(), kind=EvidenceKind.ANALOGY,
        stance=stance, source=source, source_id=sid,
        content=_render_case(rec), summary=summary, score=_score(rec),
        raw={"shared_terms": rec.get("shared_terms") or rec.get("shared_hpo") or [],
             "record": rec},
    )


async def _verdict(
    model: ChatModel, cand: Candidate, rec: dict, text: str
) -> dict:
    """Same-entity check, with the index case in view.

    The retrieved record is passed with every field rather than a whitelist:
    which field carries the diagnosis differs by corpus, and a whitelist drops
    it silently for any index that names it something else.
    """
    user = json.dumps(
        {
            "index_case": text,
            "candidate": cand.name,
            "retrieved_case": {
                k: v
                for k, v in rec.items()
                if not k.startswith("_") and v not in (None, "", [], {})
            },
        },
        ensure_ascii=False,
        default=str,
    )
    parsed = parse_json(
        await model.chat(
            ANALOGY_SAME_ENTITY, user, temperature=0.0, max_tokens=400
        )
    )
    return parsed if isinstance(parsed, dict) else {}


def _score(rec: dict) -> float | None:
    for k in ("cross_encoder_score", "rerank_score", "score", "similarity"):
        v = rec.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _render_case(rec: dict) -> str:
    """The retrieved case as text, every field kept.

    Carried alongside the GENESIS-R1 assessment so fusion and audit can inspect
    the historical presentation and its source fields directly.
    """
    if not isinstance(rec, dict):
        return str(rec)
    lines = []
    for k, v in rec.items():
        if k.startswith("_") or v in (None, "", [], {}):
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False, default=str)
        lines.append(f"{k}: {v}")
    return "\n".join(lines)
