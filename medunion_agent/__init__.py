"""MedUnion-Agent — an evidence-auditing multi-agent diagnostic workflow.

    from medunion_agent import Config, Models, Tools, diagnose

The workflow depends only on the protocols in `medunion_agent.tools.base` and
`medunion_agent.llm.base`; nothing here imports an HTTP client or an ontology
file. See `examples/` for a runnable wiring.
"""
from .types import (AgentReport, AuditReport, Candidate, CandidateStatus,
                    CycleTrace, DiagnosisResult, Evidence, EvidenceKind,
                    Phenotype, Reference, Stance)
from .agents.knowledge import RetrievalBudget
from .workflow import Config, Models, Tools, diagnose

__all__ = [
    "diagnose", "Config", "Models", "Tools", "RetrievalBudget",
    "Candidate", "Phenotype", "Evidence", "EvidenceKind", "Stance",
    "AgentReport", "AuditReport", "CandidateStatus", "CycleTrace", "Reference",
    "DiagnosisResult",
]
