"""Historical-case analogy agent.

Asks whether the index case resembles previously documented presentations.

Three representations go to each index — a phenotype term set, the free-text
narrative, and the candidate disease names — and the index uses whichever it
supports.

Each retrieved case is then checked against one candidate: is this the same
disease entity? That check is a deliberately small call, binary plus one
sentence, with no ranking authority — a model asked to judge similarity *and*
report a position does the first well and the second badly.

A retrieved case is evidence about nothing until the entity matches, so records
that fail the check are dropped rather than carried with a low score.
"""
from __future__ import annotations

import asyncio
import json

from ..llm.base import ChatModel, parse_json
from ..tools.base import CaseIndex
from ..prompts import ANALOGY_SAME_ENTITY
from ..types import (AgentReport, Candidate, Evidence, EvidenceKind, Phenotype,
                     Stance)


async def run(candidates: list[Candidate],
              phenotypes: list[Phenotype],
              text: str,
              indices: list[CaseIndex],
              model: ChatModel,
              top_k: int = 3) -> AgentReport:
    if not indices:
        return AgentReport(kind=EvidenceKind.ANALOGY,
                           notes="no case indices configured")

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
        for rec in (res or []):
            records.append((ix, rec))

    if not records:
        return AgentReport(
            kind=EvidenceKind.ANALOGY,
            failed=bool(failures) and not records,
            error="; ".join(failures) or None,
            evidence=[Evidence(candidate_key=c.key(), kind=EvidenceKind.ANALOGY,
                               stance=Stance.NEUTRAL,
                               content="No analogous cases retrieved.",
                               source="case analogy (empty)")
                      for c in candidates],
        )

    # Verdict per (candidate, record). Bounded so a large top_k across several
    # indices cannot fan out into thousands of calls.
    pairs = [(c, ix, rec) for c in candidates for ix, rec in records][:200]
    verdicts = await asyncio.gather(
        *[_verdict(model, c, rec, text) for c, _, rec in pairs],
        return_exceptions=True,
    )

    evidence: list[Evidence] = []
    for (cand, ix, rec), v in zip(pairs, verdicts):
        if isinstance(v, BaseException) or not isinstance(v, dict):
            continue
        if not v.get("same_entity"):
            continue
        shared = rec.get("shared_terms") or rec.get("shared_hpo") or []
        evidence.append(Evidence(
            candidate_key=cand.key(),
            kind=EvidenceKind.ANALOGY,
            stance=Stance.SUPPORTS,
            summary=str(v.get("justification", "")),
            content=_render_case(rec),
            source=f"{ix.name} case {rec.get('case_id', '?')}",
            source_id=str(rec.get("case_id")) if rec.get("case_id") else None,
            score=_score(rec),
            raw={"shared_terms": shared, "record": rec},
        ))

    covered = {e.candidate_key for e in evidence}
    for cand in candidates:
        if cand.key() not in covered:
            evidence.append(Evidence(
                candidate_key=cand.key(), kind=EvidenceKind.ANALOGY,
                stance=Stance.NEUTRAL,
                content="No retrieved case was judged to be the same disease entity.",
                source="case analogy (no match)",
            ))

    return AgentReport(kind=EvidenceKind.ANALOGY, evidence=evidence,
                       notes="; ".join(failures))


async def _verdict(model: ChatModel, cand: Candidate, rec: dict,
                   text: str) -> dict:
    """Same-entity check, with the index case in view.

    The retrieved record is passed with every field rather than a whitelist:
    which field carries the diagnosis differs by corpus, and a whitelist drops
    it silently for any index that names it something else.
    """
    user = json.dumps({
        "index_case": text,
        "candidate": cand.name,
        "retrieved_case": {k: v for k, v in rec.items()
                           if not k.startswith("_") and v not in (None, "", [], {})},
    }, ensure_ascii=False, default=str)
    parsed = parse_json(await model.chat(ANALOGY_SAME_ENTITY, user, temperature=0.0,
                                         max_tokens=400))
    return parsed if isinstance(parsed, dict) else {}


def _score(rec: dict) -> float | None:
    for k in ("cross_encoder_score", "rerank_score", "score", "similarity"):
        v = rec.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _render_case(rec: dict) -> str:
    """The retrieved case as text, every field kept.

    Carried alongside the one-sentence verdict so the audit can read the actual
    presentation: the verdict says *whether* the case matches, the record says
    *how*, and the second is what supports or undermines a candidate.
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
