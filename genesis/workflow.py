"""GENESIS orchestration.

The whole scheme, in the order it runs:

  1. One model proposes candidate diseases.
  2. Three evidence agents run in parallel over those candidates:
       2.1 Multi-expert consensus — is the initial differential reasonable, and
           what hypotheses were missed?
       2.2 Dynamic knowledge retrieval and deduction    — retrieve on symptoms / candidate names,
                                    reason over what comes back, summarize
       2.3 Historical-case analogy          — same, against historical case indices
  3. Evidence fusion and Evidence-consistency audit: aggregate the evidence, look for conflict. If
     another round is warranted:
       3.1 the proposing model is given the accumulated evidence and asked
           whether the differential should change
       3.2 the three agents run again, but not from scratch:
             - consensus re-examines the *new* differential against the
               evidence already gathered
             - the two retrieval agents pick up the newly introduced candidates
               and re-query at greater depth
       3.3 at most three consecutive reflection rounds

What is *not* here
------------------
The tool layer. Phenotype extraction, record condensation, ontology grounding,
the indices themselves and whatever models serve them sit behind the protocols in
`tools/base.py`. They are configuration, not workflow: swapping one encoder for
another, or a condensation model for a rule, does not touch this file.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from . import engine
from .agents import analogy, audit as audit_mod, consensus, fusion, knowledge
from .agents.knowledge import RetrievalBudget
from .llm.base import ChatModel
from .network import require_local_model, tool_allowed
from .tools.base import (
    CaseIndex,
    ConceptNormalizer,
    EvidenceSummarizer,
    ExpertMethod,
    KnowledgeSource,
    PhenotypeExtractor,
)
from .types import (
    AgentReport,
    AuditReport,
    Candidate,
    CycleTrace,
    DiagnosisResult,
    Evidence,
    EvidenceKind,
    Phenotype,
    Reference,
)

log = logging.getLogger("genesis")

# "at most three consecutive reflection rounds" — one initial evidence pass plus
# up to three revisions.
MAX_REFLECTION_ROUNDS = 3


@dataclass
class Tools:
    """Everything the workflow retrieves through. All optional.

    An absent tool disables its pathway rather than raising: a deployment
    without a case corpus should still run with two evidence agents, and that
    degradation has to be visible in the trace instead of crashing the case.
    """

    phenotype_extractor: PhenotypeExtractor | None = None
    concept_normalizer: ConceptNormalizer | None = None
    expert_methods: list[ExpertMethod] = field(default_factory=list)
    knowledge_sources: list[KnowledgeSource] = field(default_factory=list)
    case_indices: list[CaseIndex] = field(default_factory=list)
    summarizer: EvidenceSummarizer | None = None

    def for_network(self, allow_external_requests: bool) -> Tools:
        """Select permitted tools without changing the caller's configuration."""
        def select(tool):
            if tool is None or tool_allowed(tool, allow_external_requests):
                return tool
            log.info("tool omitted by access configuration: %s",
                     getattr(tool, "name", type(tool).__name__))
            return None

        def select_many(items):
            return [selected for item in items
                    if (selected := select(item)) is not None]

        return Tools(
            phenotype_extractor=select(self.phenotype_extractor),
            concept_normalizer=select(self.concept_normalizer),
            expert_methods=select_many(self.expert_methods),
            knowledge_sources=select_many(self.knowledge_sources),
            case_indices=select_many(self.case_indices),
            summarizer=select(self.summarizer),
        )


@dataclass
class Models:
    """GENESIS-R1 for diagnostic reasoning; a small model for auxiliary tasks.

    `auxiliary` checks retrieved-case relevance. The same model can be passed
    to the phenotype extractor and evidence summarizer in `tools.llm`.
    `worker` is retained only as a compatibility alias for `reasoner`.
    """

    reasoner: ChatModel
    worker: ChatModel | None = None
    auxiliary: ChatModel | None = None

    def __post_init__(self) -> None:
        if self.worker is not None and self.worker is not self.reasoner:
            raise ValueError(
                "Diagnostic stages share Models.reasoner. Pass the auxiliary "
                "model as Models(auxiliary=...), not worker."
            )
        self.worker = self.reasoner


@dataclass
class Config:
    k: int = 5  # candidates in the differential
    max_rounds: int = MAX_REFLECTION_ROUNDS
    initial_budget: RetrievalBudget = field(default_factory=RetrievalBudget.initial)
    revision_budget: RetrievalBudget = field(default_factory=RetrievalBudget.revision)
    analogy_top_k: int = 3
    discriminate_margin: int = 1
    # Per-agent switches, for ablation. Off means the pathway does not run and
    # contributes no evidence.
    use_consensus: bool = True
    use_knowledge: bool = True
    use_analogy: bool = True
    use_reflection: bool = True
    allow_external_requests: bool = True


async def diagnose(
    text: str,
    models: Models,
    tools: Tools | None = None,
    config: Config | None = None,
) -> DiagnosisResult:
    """Run the full workflow on one free-text case."""
    tools = tools or Tools()
    cfg = config or Config()
    t0 = time.monotonic()

    if not cfg.allow_external_requests:
        require_local_model(models.reasoner, "Models.reasoner")
        require_local_model(models.auxiliary, "Models.auxiliary")
    tools = tools.for_network(cfg.allow_external_requests)

    phenotypes = await _extract(text, tools)

    # ── 1. Initial differential diagnosis ──
    candidates = await engine.propose(models.reasoner, text, phenotypes, cfg.k)
    if not candidates:
        return DiagnosisResult(
            candidates=[],
            evidence=[],
            consistency_met=False,
            phenotypes=phenotypes,
            seconds=time.monotonic() - t0,
        )

    cycles: list[CycleTrace] = []
    evidence: list[Evidence] = []
    references: list[Reference] = []
    seen: set[str] = {c.key() for c in candidates}
    # First pass examines every candidate; later passes only the new ones.
    to_examine = list(candidates)
    budget = cfg.initial_budget
    consistent = False

    for round_i in range(cfg.max_rounds + 1):
        c0 = time.monotonic()

        # ── 2. three evidence pathways, in parallel ──
        reports = await _gather_evidence(
            candidates=candidates,
            examine=to_examine,
            phenotypes=phenotypes,
            text=text,
            models=models,
            tools=tools,
            cfg=cfg,
            budget=budget,
        )
        for rep in reports:
            evidence.extend(rep.evidence)

        proposed = [
            c
            for rep in reports
            for c in rep.new_candidates
            if c.key() not in seen
        ]

        # ── 3. Evidence fusion ──
        # Every round, so the differential returned always reflects what was
        # retrieved. Fusion also says whether it could settle the case.
        fused = await fusion.run(
            models.reasoner,
            text,
            phenotypes,
            candidates,
            evidence,
            proposed=proposed,
            k=cfg.k,
        )
        candidates = fused.candidates
        references = fused.references or references
        # `seen` is deliberately not updated yet: the audit classifies a candidate
        # as newly emerged by checking it against what was known before this
        # round, and folding the current set in first would make that check
        # always false.

        # ── 4. Evidence-consistency audit, when required ──
        # Skipped when fusion is satisfied: the audit exists to produce the
        # findings the engine revises against, and there is nothing to revise.
        report = _settled(fused)
        if fused.reflection_needed and cfg.use_reflection:
            report = await audit_mod.audit(
                candidates=candidates,
                evidence=evidence,
                known_before=seen,
                model=models.reasoner,
                case_text=text,
                proposed=proposed,
                discriminate_margin=cfg.discriminate_margin,
            )

        cycles.append(
            CycleTrace(
                index=round_i,
                candidates=list(candidates),
                reports=reports,
                audit=report,
                seconds=time.monotonic() - c0,
            )
        )
        consistent = report.consistent
        log.info(
            "round %d: consistent=%s, %d candidates, %d evidence records",
            round_i,
            consistent,
            len(candidates),
            len(evidence),
        )

        if consistent or not cfg.use_reflection or round_i >= cfg.max_rounds:
            break

        # Everything on the differential now counts as known.
        seen |= {c.key() for c in candidates}

        # ── 5. Revised differential diagnosis ──
        before = set(seen)
        candidates = await engine.revise(
            models.reasoner,
            text,
            phenotypes,
            candidates,
            report,
            evidence=evidence,
            k=cfg.k,
        )
        # Only the newly introduced candidates need retrieval; the rest already
        # have evidence, and consensus re-reads the whole set anyway.
        to_examine = [c for c in candidates if c.key() not in before]
        seen |= {c.key() for c in candidates}
        budget = cfg.revision_budget  # deeper retrieval from here on

        if not to_examine:
            # Revision changed only the ordering. Re-querying the same
            # candidates at the same depth would return the same records and the
            # loop would spin to its cap for nothing; audit once more with the
            # deeper budget applied to the full set instead.
            to_examine = list(candidates)

    return DiagnosisResult(
        candidates=candidates,
        evidence=evidence,
        consistency_met=consistent,
        cycles=cycles,
        phenotypes=phenotypes,
        recommended_workup=_workup(cycles),
        references=references,
        seconds=time.monotonic() - t0,
    )


# ── internals ──

async def _extract(text: str, tools: Tools) -> list[Phenotype]:
    if tools.phenotype_extractor is None:
        return []
    try:
        return await tools.phenotype_extractor.extract(text)
    except Exception as exc:
        # The engine can still reason from the raw text; losing structured
        # findings degrades the retrieval agents but must not fail the case.
        log.warning("phenotype extraction failed: %s", exc)
        return []


async def _gather_evidence(
    *,
    candidates: list[Candidate],
    examine: list[Candidate],
    phenotypes: list[Phenotype],
    text: str,
    models: Models,
    tools: Tools,
    cfg: Config,
    budget: RetrievalBudget,
) -> list[AgentReport]:
    """Run the enabled pathways concurrently.

    Consensus always sees the full differential — its job is to judge the
    current set as a whole. The two retrieval agents see `examine`, which after
    a revision is just the newly introduced candidates.
    """
    jobs: list[tuple[str, asyncio.Future]] = []

    if cfg.use_consensus and tools.expert_methods:
        jobs.append(
            (
                "consensus",
                consensus.run(
                    candidates=candidates,
                    phenotypes=phenotypes,
                    text=text,
                    methods=tools.expert_methods,
                    model=models.reasoner,
                    normalizer=tools.concept_normalizer,
                ),
            )
        )

    if cfg.use_knowledge and tools.knowledge_sources:
        jobs.append(
            (
                "knowledge",
                knowledge.run(
                    candidates=examine,
                    phenotypes=phenotypes,
                    sources=tools.knowledge_sources,
                    model=models.reasoner,
                    summarizer=tools.summarizer,
                    budget=budget,
                    text=text,
                ),
            )
        )

    if cfg.use_analogy and tools.case_indices:
        jobs.append(
            (
                "analogy",
                analogy.run(
                    candidates=examine,
                    phenotypes=phenotypes,
                    text=text,
                    indices=tools.case_indices,
                    model=models.reasoner,
                    auxiliary=models.auxiliary,
                    top_k=budget.records_per_source or cfg.analogy_top_k,
                ),
            )
        )

    if not jobs:
        return []

    done = await asyncio.gather(*(j for _, j in jobs), return_exceptions=True)
    out: list[AgentReport] = []
    for (name, _), res in zip(jobs, done):
        if isinstance(res, BaseException):
            log.warning("%s agent failed: %s", name, res)
            # Recorded, not swallowed: the audit distinguishes "no evidence
            # found" from "the pathway broke", and those mean different things.
            out.append(
                AgentReport(
                    kind=_KIND[name],
                    failed=True,
                    error=f"{type(res).__name__}: {res}",
                )
            )
        else:
            out.append(res)
    return out


_KIND = {
    "consensus": EvidenceKind.CONSENSUS,
    "knowledge": EvidenceKind.KNOWLEDGE,
    "analogy": EvidenceKind.ANALOGY,
}


def _settled(fused) -> AuditReport:
    """Preserve fusion's status when no audit is performed."""
    return AuditReport(
        consistent=not fused.reflection_needed,
        reasoning=fused.reflection_reason,
    )


def _workup(cycles: list[CycleTrace]) -> list[str]:
    """Recommended workup = the evidence gaps the final audit still had.

    What would have separated the remaining candidates is exactly what is worth
    ordering next, so this is read off the audit rather than asked for again.
    """
    return list(cycles[-1].audit.evidence_gaps) if cycles else []
