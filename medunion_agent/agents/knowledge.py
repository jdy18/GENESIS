"""Dynamic knowledge retrieval and deduction agent.

For each candidate diagnosis, queries a federation of knowledge indices along
three diagnostic axes and attaches what comes back as evidence:

    defining_features      findings that would confirm the candidate
    contradictory_findings  findings that would argue against it
    mechanism               its pathophysiological mechanism

Queries are written by the working model from the case, the candidate and the
patient's findings — retrieval is per candidate rather than per symptom, so that
what returns can discriminate between candidates rather than describing one
symptom in general.

How many queries and how many records per source is set by `RetrievalBudget`,
which widens when a case enters revision.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from ..llm.base import ChatModel, parse_json
from ..prompts import KNOWLEDGE_QUERIES
from ..tools.base import EvidenceSummarizer, KnowledgeSource
from ..types import (AgentReport, Candidate, Evidence, EvidenceKind, Phenotype,
                     Stance)


@dataclass(frozen=True)
class RetrievalBudget:
    """How wide and how deep to retrieve in one cycle."""
    queries_per_candidate: int
    records_per_source: int

    @staticmethod
    def initial() -> "RetrievalBudget":
        """First pass: one query per candidate, three records per source."""
        return RetrievalBudget(queries_per_candidate=1, records_per_source=3)

    @staticmethod
    def revision() -> "RetrievalBudget":
        """After an audit: all three axes, up to ten records per source."""
        return RetrievalBudget(queries_per_candidate=3, records_per_source=10)


# Ordered so that a budget of one asks about defining features — the question
# that most often separates two candidates.
AXES = ("defining_features", "contradictory_findings", "mechanism")


async def run(candidates: list[Candidate],
              phenotypes: list[Phenotype],
              sources: list[KnowledgeSource],
              model: ChatModel,
              summarizer: EvidenceSummarizer | None = None,
              budget: RetrievalBudget | None = None,
              text: str = "") -> AgentReport:
    """Retrieve per candidate along the axes the budget allows.

    `text` is the case. Queries built from a phenotype name list alone miss the
    findings that never became ontology terms — laboratory values, imaging
    detail, time course — which are often what discriminates two candidates.

    `summarizer=None` passes retrieved records through verbatim, which is the
    preferred mode: a condensed record carries strictly less than the record.
    """
    if not sources:
        return AgentReport(kind=EvidenceKind.KNOWLEDGE,
                           notes="no knowledge sources configured")
    budget = budget or RetrievalBudget.initial()
    axes = AXES[:max(1, min(budget.queries_per_candidate, len(AXES)))]

    present = [p.name for p in phenotypes if p.present]
    absent = [p.name for p in phenotypes if not p.present]

    queries = await asyncio.gather(
        *[_queries(model, c, present, absent, axes, text) for c in candidates],
        return_exceptions=True,
    )

    tasks, meta = [], []
    for cand, qs in zip(candidates, queries):
        if isinstance(qs, BaseException):
            # Fall back to a name-and-axis query rather than skipping the
            # candidate: a weak query still beats no evidence at all.
            qs = {a: f"{cand.name} {a.replace('_', ' ')}" for a in axes}
        for axis in axes:
            q = (qs.get(axis) or "").strip()
            if not q:
                continue
            for src in sources:
                tasks.append(src.search(q, top_k=budget.records_per_source))
                # gather() returns results without provenance, so remember which
                # candidate, axis and source each call belongs to.
                meta.append((cand, axis, src))

    if not tasks:
        return AgentReport(kind=EvidenceKind.KNOWLEDGE, notes="no queries built")

    fetched = await asyncio.gather(*tasks, return_exceptions=True)

    evidence: list[Evidence] = []
    failures: list[str] = []
    sum_tasks, sum_meta = [], []
    for (cand, axis, src), res in zip(meta, fetched):
        if isinstance(res, BaseException):
            failures.append(f"{src.name}: {type(res).__name__}")
            continue
        for rec in (res or []):
            if summarizer is None:
                # Verbatim. No stance is asserted here: whether a record supports
                # or refutes a candidate depends on the case — "lactate is
                # usually elevated in this disease" supports the candidate for
                # one patient and refutes it for another — and the audit is the
                # stage that has the case in view. A wrong REFUTES at this point
                # would silently sink a correct candidate.
                evidence.append(Evidence(
                    candidate_key=cand.key(),
                    kind=EvidenceKind.KNOWLEDGE,
                    stance=Stance.NEUTRAL,
                    source=f"{src.name} ({axis})",
                    content=_render(rec),
                    source_id=_rec_id(rec),
                    score=_rec_score(rec),
                    raw=rec,
                ))
            else:
                sum_tasks.append(summarizer.summarize(
                    cand, rec, EvidenceKind.KNOWLEDGE, src.name))
                sum_meta.append((cand, axis, src))

    if sum_tasks:
        for (cand, axis, src), ev in zip(
                sum_meta, await asyncio.gather(*sum_tasks, return_exceptions=True)):
            if isinstance(ev, BaseException) or ev is None:
                continue
            ev.candidate_key = cand.key()
            ev.kind = EvidenceKind.KNOWLEDGE
            ev.source = f"{src.name} ({axis})"
            evidence.append(ev)

    # Record an explicit empty result for candidates nothing was found for.
    # Silence would leave the audit unable to distinguish "not yet examined" from
    # "examined, and the indices hold no record" — and the second is itself
    # informative for a disease that ought to be well documented.
    covered = {e.candidate_key for e in evidence}
    for cand in candidates:
        if cand.key() not in covered:
            evidence.append(Evidence(
                candidate_key=cand.key(),
                kind=EvidenceKind.KNOWLEDGE,
                stance=Stance.NEUTRAL,
                content="No records retrieved from the knowledge indices.",
                source="knowledge retrieval (empty)",
            ))

    return AgentReport(kind=EvidenceKind.KNOWLEDGE, evidence=evidence,
                       notes="; ".join(failures))


def _render(rec: dict) -> str:
    """A retrieved record as readable text, every field kept.

    Ontology entries, article abstracts and case rows share no structure, so
    rather than mapping them onto a fixed schema — which means deciding in
    advance which fields matter — each field is laid out as `key: value`.
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


def _rec_id(rec: dict) -> str | None:
    for k in ("pmid", "id", "omim_id", "orpha_id", "hpo_id", "doc_id"):
        v = rec.get(k)
        if v:
            return str(v)
    return None


def _rec_score(rec: dict) -> float | None:
    for k in ("score", "rerank_score", "relevance", "similarity"):
        v = rec.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


async def _queries(model: ChatModel, cand: Candidate,
                   present: list[str], absent: list[str],
                   axes: tuple[str, ...], text: str) -> dict[str, str]:
    user = json.dumps({
        "clinical_case": text,
        "candidate": cand.name,
        "concept_ids": cand.concept_ids,
        "rationale": cand.rationale,
        "findings_present": present,
        "findings_absent": absent,
        "axes_requested": list(axes),
    }, ensure_ascii=False)
    parsed = parse_json(await model.chat(KNOWLEDGE_QUERIES, user, temperature=0.0,
                                         max_tokens=400))
    if not isinstance(parsed, dict):
        raise ValueError("query generation returned no object")
    return {a: str(parsed.get(a, "") or "") for a in axes}
