"""Multi-expert consensus agent.

Asks whether the working differential is reproducible across independent
diagnostic methods, and what those methods propose that the differential omits.

Agreement is computed in code from the ranked lists — presence and relative
position per method — and handed to the model as fact. The model is asked only
to interpret the pattern, so the consensus signal does not vary with prompt
wording. Counting inside a prompt instead makes a decorative consensus possible:
one where the final ranking tracks a single source and switching the others off
changes nothing, with no way to see it.

Takes any number of methods. A method that fails is recorded and the rest
proceed.
"""
from __future__ import annotations

import asyncio
import json

from ..llm.base import ChatModel, parse_json
from ..prompts import CONSENSUS_SYNTHESIS
from ..tools.base import ConceptNormalizer, ExpertMethod
from ..types import (
    AgentReport,
    Candidate,
    Evidence,
    EvidenceKind,
    Phenotype,
    Stance,
)


def _agreement(
    candidates: list[Candidate], ranked: dict[str, list[Candidate]]
) -> dict[str, dict]:
    """Presence and relative position of each candidate in each method's list.

    Position is normalized to [0, 1] (1.0 = first) so lists of different
    lengths are comparable; `votes` counts methods that named the candidate at
    all. Both are reported because they answer different questions: votes says
    how many methods recognise the disease, position says how strongly.
    """
    out: dict[str, dict] = {}
    for cand in candidates:
        key = cand.key()
        per: dict[str, float | None] = {}
        for method, lst in ranked.items():
            hit = next((c for c in lst if c.key() == key), None)
            per[method] = (
                None
                if hit is None
                else (
                    1.0
                    if len(lst) <= 1
                    else 1.0 - (hit.rank - 1) / max(len(lst) - 1, 1)
                )
            )
        votes = sum(1 for v in per.values() if v is not None)
        out[key] = {
            "name": cand.name,
            "votes": votes,
            "n_methods": len(ranked),
            "positions": per,
            "mean_position": (
                sum(v for v in per.values() if v is not None) / votes
                if votes
                else 0.0
            ),
        }
    return out


async def run(
    candidates: list[Candidate],
    phenotypes: list[Phenotype],
    text: str,
    methods: list[ExpertMethod],
    model: ChatModel,
    normalizer: ConceptNormalizer | None = None,
    max_alternatives: int = 5,
) -> AgentReport:
    """Query every method concurrently, compute agreement, then narrate it."""
    if not methods:
        return AgentReport(
            kind=EvidenceKind.CONSENSUS, notes="no expert methods configured"
        )

    results = await asyncio.gather(
        *[m.rank(phenotypes, text) for m in methods],
        return_exceptions=True,
    )

    ranked: dict[str, list[Candidate]] = {}
    failures: list[str] = []
    for method, res in zip(methods, results):
        if isinstance(res, BaseException):
            # A method that is rate-limited or down must not take the others
            # with it — discarding every result when one raises would let a
            # single 429 silently remove the whole pathway.
            failures.append(f"{method.name}: {type(res).__name__}")
            continue
        ranked[method.name] = res or []

    if not ranked:
        return AgentReport(
            kind=EvidenceKind.CONSENSUS,
            failed=True,
            error="; ".join(failures) or "all methods failed",
        )

    # Ground alternatives before comparing, so that the same disease under a
    # different label is not counted as a new candidate.
    if normalizer:
        await _ground(ranked, normalizer)

    agree = _agreement(candidates, ranked)

    # Candidates that methods named but the differential does not contain.
    known = {c.key() for c in candidates}
    tally: dict[str, tuple[Candidate, int]] = {}
    for lst in ranked.values():
        for c in lst:
            if c.key() in known:
                continue
            prev = tally.get(c.key())
            tally[c.key()] = (c, (prev[1] if prev else 0) + 1)
    # Most-supported first: an alternative named by three methods is a stronger
    # claim on the differential than one named by a single method.
    extra = [
        c for c, _ in sorted(tally.values(), key=lambda t: -t[1])
    ][:max_alternatives]

    user = json.dumps(
        {
            # The case comes first and in full. Judging whether a differential is
            # reasonable is not possible from ranked name lists alone, and a stage
            # that sees less than the case sees less than a plain model call.
            "clinical_case": text,
            "extracted_findings_present": [p.name for p in phenotypes if p.present],
            "extracted_findings_absent": [
                p.name for p in phenotypes if not p.present
            ],
            "working_differential": [
                {
                    "rank": c.rank,
                    "name": c.name,
                    "rationale": c.rationale,
                    "supporting_findings": c.supporting_findings,
                    "contradictory_findings": c.contradictory_findings,
                }
                for c in sorted(candidates, key=lambda c: c.rank)
            ],
            "methods": list(ranked),
            "method_rankings": {
                m: [{"rank": c.rank, "name": c.name} for c in lst]
                for m, lst in ranked.items()
            },
            "computed_agreement": list(agree.values()),
            "candidates_absent_from_differential": [c.name for c in extra],
            "failed_methods": failures,
        },
        ensure_ascii=False,
    )

    try:
        reply = (
            parse_json(
                await model.chat(CONSENSUS_SYNTHESIS, user, temperature=0.2)
            )
            or {}
        )
    except Exception as exc:
        # Agreement is already computed; losing the narration is a degradation,
        # not a failure of the pathway.
        reply = {}
        failures.append(f"synthesis: {type(exc).__name__}")

    by_name = {c.name.casefold(): c for c in candidates}
    evidence: list[Evidence] = []
    for item in reply.get("assessments") or []:
        cand = by_name.get(str(item.get("candidate", "")).casefold())
        if not cand:
            continue
        info = agree.get(cand.key(), {})
        evidence.append(
            Evidence(
                candidate_key=cand.key(),
                kind=EvidenceKind.CONSENSUS,
                stance=_stance(item.get("stance")),
                content=str(item.get("summary", "")),
                source="multi-expert consensus (%s)" % ", ".join(ranked),
                score=info.get("mean_position"),
                raw=info,
            )
        )

    # Every candidate gets a consensus record even when the model skipped it —
    # the audit reads absence of evidence as an evidence gap, so a silent gap
    # here would be indistinguishable from "no method recognised this disease".
    covered = {e.candidate_key for e in evidence}
    for cand in candidates:
        if cand.key() in covered:
            continue
        info = agree.get(cand.key(), {})
        votes, n = info.get("votes", 0), info.get("n_methods", len(ranked))
        evidence.append(
            Evidence(
                candidate_key=cand.key(),
                kind=EvidenceKind.CONSENSUS,
                stance=(
                    Stance.SUPPORTS
                    if votes > n / 2
                    else (Stance.NEUTRAL if votes else Stance.REFUTES)
                ),
                summary=f"Named by {votes}/{n} independent methods.",
                source="multi-expert consensus (computed)",
                score=info.get("mean_position"),
                raw=info,
            )
        )

    alt_reason = {
        str(a.get("name", "")).casefold(): str(a.get("rationale", ""))
        for a in (reply.get("alternatives") or [])
    }
    for c in extra:
        c.rationale = alt_reason.get(c.name.casefold(), c.rationale)

    return AgentReport(
        kind=EvidenceKind.CONSENSUS,
        evidence=evidence,
        new_candidates=extra,
        notes="; ".join(failures),
    )


async def _ground(
    ranked: dict[str, list[Candidate]], normalizer: ConceptNormalizer
) -> None:
    """Attach ontology ids in one batched call, then let `key()` consolidate."""
    everything = [c for lst in ranked.values() for c in lst]
    names = [c.name for c in everything]
    if not names:
        return
    try:
        ids = await normalizer.normalize(names)
    except Exception:
        return  # unnormalized names still compare by string
    for cand, mapping in zip(everything, ids):
        if mapping:
            cand.concept_ids.update(mapping)


def _stance(raw: object) -> Stance:
    try:
        return Stance(str(raw).strip().lower())
    except ValueError:
        return Stance.NEUTRAL
