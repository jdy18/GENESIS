#!/usr/bin/env python3
"""Runnable end-to-end example with stub tools — no network, no GPU.

    python3 examples/minimal.py

Its job is to show model and tool wiring and to make completed evidence cycles
observable. The scripted responses may settle after the initial cycle.

Replace each stub with a real implementation and nothing in `genesis/`
changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from genesis import Config, Models, Tools, diagnose  # noqa: E402
from genesis.types import (  # noqa: E402
    Candidate,
    Evidence,
    EvidenceKind,
    Phenotype,
    Stance,
)

CASE = """32-year-old woman, progressive proximal muscle weakness over 8 months,
exercise intolerance, bilateral ptosis. Lactate elevated at 4.2 mmol/L.
No family history of neuromuscular disease. Thyroid function normal.
Muscle biopsy: ragged red fibres on modified Gomori trichrome."""


# ── stub models ──

class StubReasoner:
    """Stands in for the 14 B diagnostic engine.

    Returns a different differential on the revision call so the example shows a
    candidate being introduced rather than just reordered.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        self.calls += 1
        revising = "revising a differential" in system
        if not revising:
            cands = [
                ("Mitochondrial myopathy", "Ragged red fibres with elevated lactate."),
                ("Myasthenia gravis", "Ptosis and fatigable weakness."),
                ("Polymyositis", "Proximal weakness."),
            ]
        else:
            cands = [
                ("MELAS syndrome", "Audit noted the specific mitochondrial subtype."),
                ("Mitochondrial myopathy", "Retained; ragged red fibres."),
                ("Myasthenia gravis", "Demoted; lactate and biopsy fit poorly."),
            ]
        return json.dumps(
            {
                "candidates": [
                    {
                        "rank": i,
                        "name": n,
                        "supporting_findings": ["ragged red fibres"],
                        "contradictory_findings": [],
                        "unresolved_questions": ["genetic testing"],
                        "rationale": r,
                    }
                    for i, (n, r) in enumerate(cands, 1)
                ]
            }
        )


class StubGENESISR1:
    """One diagnostic model for initial diagnosis, evidence reasoning and fusion."""

    def __init__(self) -> None:
        self.reasoner = StubReasoner()

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        if "You are a diagnostician" in system or "revising a differential" in system:
            return await self.reasoner.chat(system, user, temperature=temperature,
                                            max_tokens=max_tokens)
        if "retrieval queries" in system:
            return json.dumps(
                {
                    "defining_features": "ragged red fibres lactate",
                    "contradictory_findings": "normal lactate",
                    "mechanism": "mitochondrial respiratory chain",
                }
            )
        if "SAME disease entity" in system:
            return json.dumps(
                {
                    "same_entity": True,
                    "justification": "Indexed case reports the same entity.",
                }
            )
        if "You perform Historical-case analogy" in system:
            payload = json.loads(user)
            return json.dumps({"assessments": [{
                "candidate": check["candidate"], "stance": "neutral",
                "summary": "Related historical presentation; the mitochondrial subtype remains unresolved.",
                "sources": [check["source"]],
            } for check in payload["same_entity_checks"] if check["same_entity"]],
                "alternatives": []})
        if "producing a final ranked differential" in system:
            # Fusion: promote whatever the consensus agent proposed, so the
            # example shows evidence changing the ranking.
            payload = json.loads(user)
            names = [d["name"] for d in payload["working_differential"]]
            alts = [a["name"] for a in payload["alternatives_proposed_by_agents"]]
            ordered = alts + [n for n in names if n not in alts]
            return json.dumps(
                {
                    "evidence_cross_validation": {
                        "consensus_diagnoses": ordered[:1],
                        "contested_diagnoses": ordered[1:],
                        "newly_emerged_diagnoses": alts,
                    },
                    "q1_diagnoses": [
                        {
                            "name": n,
                            "rarity": "rare" if i == 0 else "common",
                            "confidence": f"{80 - 20 * i}%",
                            "reasoning": (
                                f"Ranked {i + 1} on the retrieved evidence [1]."
                            ),
                            "exams": (
                                "mtDNA sequencing" if i == 0 else "routine workup"
                            ),
                        }
                        for i, n in enumerate(ordered[:3])
                    ],
                    "references": [
                        {
                            "id": "[1]",
                            "type": "article",
                            "description": "Retrieved record.",
                            "source": "stub index",
                        }
                    ],
                    "reflection_needed": len(alts) > 0,
                    "reflection_reason": "Alternative introduced." if alts else "",
                }
            )
        if "auditing the evidence" in system:
            # Stop once MELAS is *in the differential* — not merely mentioned.
            # Checking `"MELAS" in user` was wrong: the consensus agent proposes
            # MELAS as an alternative in round 0, so the string is already in the
            # payload and the stub declared the case settled before any
            # reflection happened.
            payload = json.loads(user)
            in_diff = any("MELAS" in d["name"] for d in payload["differential"])
            has_melas = in_diff
            return json.dumps(
                {
                    "unsupported_claims": (
                        []
                        if has_melas
                        else [
                            "Myasthenia gravis rationale is unsupported by the biopsy."
                        ]
                    ),
                    "conflicting_findings": (
                        []
                        if has_melas
                        else [
                            "Elevated lactate conflicts with a purely "
                            "neuromuscular cause."
                        ]
                    ),
                    "evidence_gaps": (
                        []
                        if has_melas
                        else [
                            "Mitochondrial subtype not established; mtDNA testing "
                            "needed."
                        ]
                    ),
                    "reasoning": (
                        "Consistent." if has_melas else "Subtype unresolved."
                    ),
                }
            )
        # consensus narration
        return json.dumps(
            {
                "assessments": [
                    {
                        "candidate": "Mitochondrial myopathy",
                        "stance": "supports",
                        "summary": "Named first by both methods.",
                    }
                ],
                "alternatives": [
                    {
                        "name": "MELAS syndrome",
                        "rationale": "Both methods list it.",
                    }
                ],
            }
        )


# ── stub tools ──

class StubAuxiliary:
    """Scripted retrieved-case relevance check for the auxiliary-model role."""

    async def chat(self, system, user, **kwargs):
        return json.dumps({
            "same_entity": True,
            "justification": "Indexed case reports the same entity.",
        })

class StubExtractor:
    async def extract(self, text: str) -> list[Phenotype]:
        return [
            Phenotype("Proximal muscle weakness", "HP:0003701"),
            Phenotype("Ptosis", "HP:0000508"),
            Phenotype("Elevated circulating lactate", "HP:0002151"),
            Phenotype("Ragged red muscle fibres", "HP:0003200"),
            Phenotype("Family history of neuromuscular disease", present=False),
        ]


class StubMethod:
    def __init__(self, name: str, ranking: list[str]) -> None:
        self.name = name
        self._ranking = ranking

    async def rank(self, phenotypes, text=None) -> list[Candidate]:
        return [Candidate(name=n, rank=i) for i, n in enumerate(self._ranking, 1)]


class StubKnowledge:
    name = "hpo-snapshot"

    async def search(self, query: str, top_k: int = 3) -> list[dict]:
        return [
            {"title": f"Record for: {query[:40]}", "id": f"REC{i}"}
            for i in range(1, top_k + 1)
        ]


class StubCases:
    name = "case-index"

    async def search(
        self, phenotypes, text=None, disease_names=None, top_k: int = 3
    ) -> list[dict]:
        return [
            {
                "case_id": f"CASE{i}",
                "diagnosis": "MELAS syndrome",
                "shared_terms": ["Ragged red muscle fibres"],
                "cross_encoder_score": 0.9 - 0.1 * i,
            }
            for i in range(1, min(top_k, 3) + 1)
        ]


class StubSummarizer:
    async def summarize(self, candidate, record, kind, source) -> Evidence | None:
        return Evidence(
            candidate_key=candidate.key(),
            kind=kind,
            stance=Stance.SUPPORTS,
            summary=f"{record.get('title', record.get('case_id'))}",
            source=source,
            source_id=str(record.get("id") or ""),
        )


class StubNormalizer:
    async def normalize(self, names: list[str]) -> list[dict]:
        table = {
            "melas syndrome": {"MONDO": "0010196"},
            "mitochondrial myopathy": {"MONDO": "0018276"},
        }
        return [table.get(n.strip().casefold(), {}) for n in names]


# ── run ──

async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="  %(message)s")

    result = await diagnose(
        CASE,
        models=Models(reasoner=StubGENESISR1(), auxiliary=StubAuxiliary()),
        tools=Tools(
            phenotype_extractor=StubExtractor(),
            concept_normalizer=StubNormalizer(),
            expert_methods=[
                StubMethod(
                    "phenotype-ranker",
                    ["Mitochondrial myopathy", "MELAS syndrome", "Polymyositis"],
                ),
                StubMethod(
                    "case-matcher",
                    [
                        "MELAS syndrome",
                        "Mitochondrial myopathy",
                        "Myasthenia gravis",
                    ],
                ),
            ],
            knowledge_sources=[StubKnowledge()],
            case_indices=[StubCases()],
            summarizer=StubSummarizer(),
        ),
        config=Config(k=3),
    )

    print(f"\n  consistency met : {result.consistency_met}")
    print(f"  evidence cycles: {len(result.cycles)}   ({result.seconds:.2f}s)")
    print(
        f"  phenotypes      : {len(result.phenotypes)} "
        f"({sum(1 for p in result.phenotypes if not p.present)} pertinent negative)"
    )
    print("\n  final differential")
    for c in sorted(result.candidates, key=lambda c: c.rank):
        print(f"    {c.rank}. {c.name}")
        print(f"       {c.rationale}")

    print(f"\n  evidence: {len(result.evidence)} records")
    for kind in EvidenceKind:
        n = sum(1 for e in result.evidence if e.kind is kind)
        print(f"    {kind.value:<10} {n}")

    print("\n  per round")
    for cy in result.cycles:
        new = [n for n, s in cy.audit.status.items() if s.value == "emerged"]
        print(
            f"    round {cy.index}: consistent={cy.audit.consistent}  "
            f"candidates={len(cy.candidates)}  emerged={len(new)}  "
            f"gaps={len(cy.audit.evidence_gaps)}"
        )

    if result.recommended_workup:
        print("\n  recommended workup")
        for w in result.recommended_workup:
            print(f"    - {w}")


if __name__ == "__main__":
    asyncio.run(main())
