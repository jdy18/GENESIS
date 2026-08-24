"""Evidence-consistency audit.

Integrates the evidence gathered for each candidate — cross-method agreement,
rank, supporting and contradictory records, source and analogous-case similarity
— and classifies every candidate as one of:

    consensus   supported, with nothing refuting it
    contested   refuted by at least one pathway
    emerged     introduced during this cycle, not previously in the differential

A candidate set has not settled when either holds:

    1. high-confidence evidence cannot be reconciled with a candidate's stated
       rationale; or
    2. the evidence does not separate the leading candidates.

Failing either produces a structured report — unsupported claims, conflicting
findings, evidence gaps, proposed alternatives — which is what the reasoning
engine revises against.

The classification and both conditions are computed in code; the model is asked
only to articulate the findings, so the loop's stopping behaviour is a function
of the evidence rather than of prompt wording.
"""
from __future__ import annotations

import json

from ..llm.base import ChatModel, parse_json
from ..prompts import AUDIT_FINDINGS
from ..types import (
    AuditReport,
    Candidate,
    CandidateStatus,
    Evidence,
    EvidenceKind,
    Stance,
)


def classify(
    candidates: list[Candidate],
    evidence: list[Evidence],
    known_before: set[str],
) -> dict[str, CandidateStatus]:
    """consensus / contested / emerged, per candidate.

    - emerged   : not in the differential at the start of this cycle
    - contested : at least one pathway refutes it while another supports it
    - consensus : supported, with nothing refuting
    """
    by_cand: dict[str, list[Evidence]] = {}
    for ev in evidence:
        by_cand.setdefault(ev.candidate_key, []).append(ev)

    out: dict[str, CandidateStatus] = {}
    for cand in candidates:
        key = cand.key()
        if key not in known_before:
            out[key] = CandidateStatus.EMERGED
            continue
        evs = by_cand.get(key, [])
        supports = any(e.stance is Stance.SUPPORTS for e in evs)
        refutes = any(e.stance is Stance.REFUTES for e in evs)
        out[key] = (
            CandidateStatus.CONTESTED
            if (refutes and supports)
            else (
                CandidateStatus.CONTESTED
                if refutes
                else CandidateStatus.CONSENSUS
                if supports
                else CandidateStatus.CONTESTED
            )
        )
    return out


def _discriminable(
    candidates: list[Candidate],
    evidence: list[Evidence],
    status: dict[str, CandidateStatus],
    margin: int = 1,
) -> bool:
    """Is the evidence enough to separate the leaders?

    Counts supporting pathways per candidate — pathways, not records, so that
    one source returning ten papers cannot outvote two independent pathways.
    The top candidate must lead by at least `margin` supporting pathways.
    """
    if len(candidates) <= 1:
        return True
    per: dict[str, set[EvidenceKind]] = {}
    for ev in evidence:
        if ev.stance is Stance.SUPPORTS:
            per.setdefault(ev.candidate_key, set()).add(ev.kind)
    counts = sorted((len(per.get(c.key(), set())) for c in candidates), reverse=True)
    if counts[0] == 0:
        return False  # nothing supports anything
    return counts[0] - counts[1] >= margin


async def audit(
    candidates: list[Candidate],
    evidence: list[Evidence],
    known_before: set[str],
    model: ChatModel,
    case_text: str = "",
    proposed: list[Candidate] | None = None,
    discriminate_margin: int = 1,
) -> AuditReport:
    """Integrate the evidence and decide whether the candidate set has settled.

    `case_text` must be the full case: the criterion is whether evidence can be
    reconciled with a candidate's rationale, which is only checkable against the
    case that rationale was written about.
    """
    status = classify(candidates, evidence, known_before)

    # Condition 2 of the two in Methods: is the evidence enough to separate the
    # leaders? Computable from the evidence alone, so it is decided before the
    # model is consulted.
    indistinguishable = not _discriminable(
        candidates, evidence, status, discriminate_margin
    )

    # Condition 1 — "high-confidence evidence could not be reconciled with the
    # original diagnostic rationale" — is partly a reading task: a rationale can
    # be contradicted by evidence that, taken alone, supports a different
    # candidate. So the verdict is assembled in two steps, the structural signal
    # below plus the model's findings once it replies.
    refuted = [
        c
        for c in candidates
        if status.get(c.key()) is CandidateStatus.CONTESTED
        and any(
            e.candidate_key == c.key()
            and e.stance is Stance.REFUTES
            and (e.score is None or e.score >= 0.5)
            for e in evidence
        )
    ]

    by_cand: dict[str, list[Evidence]] = {}
    for ev in evidence:
        by_cand.setdefault(ev.candidate_key, []).append(ev)

    # Evidence goes in whole. Volume is controlled at retrieval time by
    # RetrievalBudget, not by trimming here.
    per_candidate = {
        c.key(): [
            f"[{e.kind.value} | {e.stance.value} | {e.source}]\n{e.text()}"
            for e in by_cand.get(c.key(), [])
        ]
        for c in candidates
    }

    user = json.dumps(
        {
            # The case, in full and first. The criterion this function evaluates is
            # whether evidence can be reconciled with a rationale, and a rationale
            # can only be checked against the case it was written about.
            "clinical_case": case_text,
            "differential": [
                {
                    "rank": c.rank,
                    "name": c.name,
                    "rationale": c.rationale,
                    "supporting_findings": c.supporting_findings,
                    "contradictory_findings": c.contradictory_findings,
                    "unresolved_questions": c.unresolved_questions,
                    "status": status.get(c.key(), CandidateStatus.CONTESTED).value,
                    "evidence": per_candidate.get(c.key(), []),
                }
                for c in sorted(candidates, key=lambda c: c.rank)
            ],
            "alternatives_proposed_by_agents": [c.name for c in (proposed or [])],
            "computed": {
                "candidates_with_refuting_evidence": [c.name for c in refuted],
                "evidence_insufficient_to_discriminate": indistinguishable,
            },
        },
        ensure_ascii=False,
    )

    try:
        reply = (
            parse_json(await model.chat(AUDIT_FINDINGS, user, temperature=0.0))
            or {}
        )
    except Exception as exc:
        # The verdict is already decided in code; only the narrative is lost.
        reply = {"reasoning": f"audit narration unavailable: {type(exc).__name__}"}

    unsupported = [str(x) for x in (reply.get("unsupported_claims") or [])]
    conflicting = [str(x) for x in (reply.get("conflicting_findings") or [])]
    gaps = [str(x) for x in (reply.get("evidence_gaps") or [])]
    if indistinguishable and not gaps:
        gaps.append("Evidence does not separate the leading candidates.")

    # Final verdict: the structural signals *and* what the audit found. Any of
    # the four means the candidate set has not settled, which is what starts
    # another reflection round.
    consistent = not (refuted or indistinguishable or conflicting or gaps)

    return AuditReport(
        consistent=consistent,
        status=status,
        unsupported_claims=[
            str(x) for x in (reply.get("unsupported_claims") or [])
        ],
        conflicting_findings=[
            str(x) for x in (reply.get("conflicting_findings") or [])
        ],
        evidence_gaps=gaps,
        proposed_alternatives=list(proposed or []),
        reasoning=str(reply.get("reasoning", "")),
    )
