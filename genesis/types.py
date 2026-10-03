"""Data structures exchanged between the reasoning engine, the evidence agents
and the consistency audit.

The reasoning engine returns, per candidate, its rank, supporting findings,
potentially contradictory findings, unresolved questions and diagnostic
rationale; those records are the common input to the three evidence agents.

Plain dataclasses — no pydantic, no framework — so the workflow can be read and
reused without adopting a particular stack.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Phenotype ──

@dataclass
class Phenotype:
    """One normalized clinical finding.

    `term_id` is optional — a finding that could not be grounded in an ontology
    is still a finding, and dropping it loses information the case stated.
    """

    name: str
    term_id: str | None = None          # e.g. "HP:0001250"
    present: bool = True                # False => pertinent negative
    source_span: str | None = None       # verbatim text this came from


# ── Candidate diagnosis ──

@dataclass
class Candidate:
    """A candidate diagnosis and the reasoning attached to it."""

    name: str
    rank: int
    supporting_findings: list[str] = field(default_factory=list)
    contradictory_findings: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    rationale: str = ""
    # Fields the fusion step fills in. Kept on Candidate rather than in a
    # separate structure so that one object carries everything about a candidate
    # from proposal through to the final answer.
    rarity: str = ""                    # e.g. "rare" / "common"
    confidence: str = ""                # as written, e.g. "70%"
    exams: str = ""                     # suggested next workup for this candidate
    # Filled in by normalization. Several namespaces are kept so that labels
    # resolving to the same entity can be consolidated.
    concept_ids: dict[str, str] = field(default_factory=dict)

    def key(self) -> str:
        """Identity used when consolidating candidates across agents.

        Prefers an ontology id so that "Gaucher disease" and "戈谢病" collapse;
        falls back to a casefolded name when nothing is grounded.
        """
        for ns in ("MONDO", "OMIM", "ORDO", "ICD10"):
            if self.concept_ids.get(ns):
                return f"{ns}:{self.concept_ids[ns]}"
        return self.name.strip().casefold()


# ── Evidence ──

class EvidenceKind(str, Enum):
    """Which of the three pathways produced a record."""

    CONSENSUS = "consensus"
    KNOWLEDGE = "knowledge"
    ANALOGY = "analogy"


class Stance(str, Enum):
    """Whether a record argues for or against the candidate it is attached to.

    Explicit because the audit must be able to find evidence that cannot be
    reconciled with a candidate's rationale, which requires refuting records to
    be labelled rather than pooled with supporting ones.
    """

    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"


@dataclass
class Evidence:
    """One retrieved record, bound to the candidate it speaks to.

    `content` is the retrieved text or relevant passages selected by the
    configured adapter. It is what downstream prompts read; `raw` retains the
    source payload when supplied by the adapter.

    `summary` holds an optional gloss or the agent's assessment of the record.
    Downstream reasoning receives it separately from `content`, so an assessment
    is kept distinct from the retrieved text or selected passages.
    """

    candidate_key: str
    kind: EvidenceKind
    stance: Stance
    source: str                          # human-readable provenance
    content: str = ""                    # retrieved text or selected passages
    summary: str = ""                    # optional short gloss
    source_id: str | None = None         # PMID / OMIM id / case id, when known
    score: float | None = None           # retrieval or cross-encoder score
    raw: Any = None                      # untouched tool payload, for traces

    def text(self) -> str:
        """What a prompt should show for this record: the record itself."""
        return self.content or self.summary


@dataclass
class AgentReport:
    """What one evidence agent returns for the whole candidate set."""

    kind: EvidenceKind
    evidence: list[Evidence] = field(default_factory=list)
    # Credible alternatives absent from the working differential. The consensus
    # and analogy agents can both propose these.
    new_candidates: list[Candidate] = field(default_factory=list)
    notes: str = ""
    failed: bool = False                 # agent errored; audit must know
    error: str | None = None
    # Parsed model output, retained separately from the original evidence.
    synthesis: dict[str, Any] | None = None


@dataclass
class Reference:
    """A cited source in the final answer."""

    id: str                              # citation marker, e.g. "[1]"
    type: str = ""                       # guideline / case report / article / tool
    description: str = ""
    source: str = ""                     # title, and URL when available


@dataclass
class FusionResult:
    """What the fusion agent returns: the answer, plus whether to reflect."""

    candidates: list[Candidate]
    references: list[Reference] = field(default_factory=list)
    reflection_needed: bool = False
    reflection_reason: str = ""


# ── Audit ──

class CandidateStatus(str, Enum):
    """Classification applied during evidence integration."""

    CONSENSUS = "consensus"
    CONTESTED = "contested"
    EMERGED = "emerged"


@dataclass
class AuditReport:
    """Result of the evidence-consistency audit for one cycle.

    `consistent=False` triggers another revision cycle; the fields below are
    what the reasoning engine is given to revise against.
    """

    consistent: bool
    status: dict[str, CandidateStatus] = field(default_factory=dict)
    unsupported_claims: list[str] = field(default_factory=list)
    conflicting_findings: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    proposed_alternatives: list[Candidate] = field(default_factory=list)
    reasoning: str = ""


# ── Final result ──

@dataclass
class CycleTrace:
    """One pass of evidence collection + audit, kept for the provenance chain."""

    index: int
    candidates: list[Candidate]
    reports: list[AgentReport]
    audit: AuditReport
    seconds: float = 0.0


@dataclass
class DiagnosisResult:
    """Final output: ranked differential, per-candidate reasoning, evidence,
    provenance, and whether the consistency criterion was met.
    """

    candidates: list[Candidate]
    evidence: list[Evidence]
    consistency_met: bool
    cycles: list[CycleTrace] = field(default_factory=list)
    phenotypes: list[Phenotype] = field(default_factory=list)
    recommended_workup: list[str] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def top_k(self) -> list[str]:
        return [c.name for c in sorted(self.candidates, key=lambda c: c.rank)]

    def to_dict(self) -> dict:
        """The answer as a JSON-serialisable dict.

        Field names follow the report schema the workflow has always emitted, so
        that existing consumers and evaluation scripts keep working:
        `q1_diagnoses` for the ranked differential, `evidence_cross_validation`
        for the candidate classification, `references` for citations, and
        `reflection_needed` for whether the consistency criterion was met.
        """
        last = self.cycles[-1].audit if self.cycles else None
        status = last.status if last else {}
        by_status: dict[str, list[str]] = {
            "consensus_diagnoses": [],
            "contested_diagnoses": [],
            "newly_emerged_diagnoses": [],
        }
        keyed = {c.key(): c for c in self.candidates}
        for key, st in status.items():
            cand = keyed.get(key)
            if not cand:
                continue
            bucket = {
                "consensus": "consensus_diagnoses",
                "contested": "contested_diagnoses",
                "emerged": "newly_emerged_diagnoses",
            }[st.value]
            by_status[bucket].append(cand.name)
        return {
            "evidence_cross_validation": by_status,
            "q1_diagnoses": [
                {
                    "name": c.name,
                    "rarity": c.rarity,
                    "confidence": c.confidence,
                    "reasoning": c.rationale,
                    "exams": c.exams,
                }
                for c in sorted(self.candidates, key=lambda c: c.rank)
            ],
            "references": [
                {
                    "id": r.id,
                    "type": r.type,
                    "description": r.description,
                    "source": r.source,
                }
                for r in self.references
            ],
            "reflection_needed": not self.consistency_met,
            "reflection_reason": (
                ""
                if self.consistency_met
                else (
                    (
                        "; ".join((last.evidence_gaps + last.conflicting_findings)[:3])
                        or last.reasoning
                    )
                    if last
                    else ""
                )
            ),
        }
