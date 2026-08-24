#!/usr/bin/env python3
"""Run the workflow over `minimal_dataset/` with file-backed tools.

    python3 examples/run_dataset.py                    # all cases, stub model
    python3 examples/run_dataset.py --case case_003
    python3 examples/run_dataset.py --base-url http://localhost:8000/v1 \
                                    --model your-model

Without `--base-url` the workflow runs against a scripted model, so the command
works offline and the control flow is visible. With one, the same tools are
driven by a real model — which is the shortest path from this repository to a
working setup.

The tool classes below read `minimal_dataset/indices/*.json`. They are complete
implementations of four of the six tool protocols, in about eighty lines, and
show what each one has to return.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "minimal_dataset"

from genesis import Config, Models, Tools, diagnose  # noqa: E402
from genesis.types import Candidate, Phenotype  # noqa: E402


# ── tools, backed by the JSON files ──

class FileKnowledge:
    """Keyword overlap over `indices/knowledge.json`.

    Deliberately naive — a real deployment puts an embedding or BM25 index here.
    What matters for the protocol is the shape: a list of dicts, best first.
    """

    name = "knowledge-index"

    def __init__(self) -> None:
        self._records = json.loads((DATA / "indices/knowledge.json").read_text("utf-8"))

    async def search(self, query: str, top_k: int = 3) -> list[dict]:
        terms = {t for t in query.casefold().split() if len(t) > 3}
        scored = []
        for rec in self._records:
            blob = f"{rec['title']} {rec['text']}".casefold()
            hits = sum(1 for t in terms if t in blob)
            if hits:
                scored.append((hits, rec))
        scored.sort(key=lambda p: -p[0])
        return [rec for _, rec in scored[:top_k]]


class FileCases:
    """Shared-phenotype matching over `indices/cases.json`."""

    name = "case-index"

    def __init__(self) -> None:
        self._records = json.loads((DATA / "indices/cases.json").read_text("utf-8"))

    async def search(
        self,
        phenotypes: list[Phenotype],
        text: str | None = None,
        disease_names: list[str] | None = None,
        top_k: int = 3,
    ) -> list[dict]:
        present = {p.name.casefold() for p in phenotypes if p.present}
        wanted = {n.casefold() for n in (disease_names or [])}
        scored = []
        for rec in self._records:
            shared = sum(
                1
                for t in rec.get("shared_terms", [])
                if t.casefold() in present
            )
            named = 1 if rec.get("diagnosis", "").casefold() in wanted else 0
            if shared or named:
                scored.append((named * 10 + shared, rec))
        scored.sort(key=lambda p: -p[0])
        return [rec for _, rec in scored[:top_k]]


class FileExpert:
    """One method's ranked list out of `indices/expert_rankings.json`."""

    def __init__(self, name: str, case_id: str) -> None:
        self.name = name
        table = json.loads((DATA / "indices/expert_rankings.json").read_text("utf-8"))
        self._ranking = table.get(case_id, {}).get(name, [])

    async def rank(
        self, phenotypes: list[Phenotype], text: str | None = None
    ) -> list[Candidate]:
        return [
            Candidate(name=n, rank=i)
            for i, n in enumerate(self._ranking, start=1)
        ]


class GivenPhenotypes:
    """Returns the findings the case file already carries.

    A real deployment puts an extraction model here. Cases without a
    `phenotypes` block get an empty list, which is legitimate: the workflow reads
    the narrative either way.
    """

    def __init__(self, case: dict) -> None:
        self._items = case.get("phenotypes") or []

    async def extract(self, text: str) -> list[Phenotype]:
        return [
            Phenotype(
                name=p["name"],
                term_id=p.get("term_id"),
                present=p.get("present", True),
            )
            for p in self._items
        ]


# ── scripted model, for the offline path ──

class ScriptedModel:
    """Answers each prompt role plausibly, using the case's own gold answer.

    This is a test double, not a diagnostic system: it exists so the command runs
    without a server. Pass `--base-url` to see what a real model does.
    """

    def __init__(self, case: dict) -> None:
        self._gold = case["gold_diagnosis"]
        self._alt = "Mitochondrial myopathy"
        self._round = 0

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        if "retrieval queries" in system:
            return json.dumps(
                {
                    "defining_features": self._gold,
                    "contradictory_findings": f"{self._gold} atypical",
                    "mechanism": f"{self._gold} mechanism",
                }
            )
        if "SAME disease entity" in system:
            payload = json.loads(user)
            same = (
                payload["retrieved_case"].get("diagnosis", "").casefold()
                == payload["candidate"].casefold()
            )
            return json.dumps(
                {
                    "same_entity": same,
                    "justification": (
                        "Diagnosis label matches." if same else "Different entity."
                    ),
                }
            )
        if "diagnostic evidence auditor" in system:
            return json.dumps({"assessments": [], "alternatives": []})
        if "producing a final ranked differential" in system:
            payload = json.loads(user)
            names = [d["name"] for d in payload["working_differential"]]
            alts = [a["name"] for a in payload["alternatives_proposed_by_agents"]]
            order = (
                [self._gold]
                + [n for n in alts if n != self._gold]
                + [n for n in names if n != self._gold]
            )
            seen, ordered = set(), []
            for n in order:
                if n not in seen:
                    seen.add(n)
                    ordered.append(n)
            return json.dumps(
                {
                    "evidence_cross_validation": {
                        "consensus_diagnoses": ordered[:1],
                        "contested_diagnoses": ordered[1:3],
                        "newly_emerged_diagnoses": [
                            n for n in alts if n not in names
                        ],
                    },
                    "q1_diagnoses": [
                        {
                            "name": n,
                            "rarity": "rare",
                            "confidence": f"{85 - 25 * i}%",
                            "reasoning": (
                                f"Ranked {i + 1} on the retrieved evidence [1]."
                            ),
                            "exams": "confirmatory testing",
                        }
                        for i, n in enumerate(ordered[:3])
                    ],
                    "references": [
                        {
                            "id": "[1]",
                            "type": "reference summary",
                            "description": "Retrieved record.",
                            "source": "minimal_dataset",
                        }
                    ],
                    "reflection_needed": False,
                    "reflection_reason": "",
                }
            )
        if "auditing the evidence" in system:
            return json.dumps(
                {
                    "unsupported_claims": [],
                    "conflicting_findings": [],
                    "evidence_gaps": [],
                    "reasoning": "Consistent.",
                }
            )
        # proposing or revising the differential
        self._round += 1
        first = self._alt if self._round == 1 else self._gold
        second = self._gold if self._round == 1 else self._alt
        return json.dumps(
            {
                "candidates": [
                    {
                        "rank": 1,
                        "name": first,
                        "supporting_findings": [],
                        "contradictory_findings": [],
                        "unresolved_questions": [],
                        "rationale": "Initial impression.",
                    },
                    {
                        "rank": 2,
                        "name": second,
                        "supporting_findings": [],
                        "contradictory_findings": [],
                        "unresolved_questions": [],
                        "rationale": "Considered.",
                    },
                ]
            }
        )


# ── run ──

def matches(answer: str, case: dict) -> bool:
    """Does the top answer name the reference diagnosis?"""
    accept = [case["gold_diagnosis"], *case.get("gold_synonyms", [])]
    got = answer.casefold()
    return any(a.casefold() in got or got in a.casefold() for a in accept)


async def run_case(path: Path, args) -> bool:
    case = json.loads(path.read_text("utf-8"))
    if args.base_url:
        from genesis.llm.openai_compat import OpenAIChat
        model = OpenAIChat(args.base_url, args.model, api_key=args.api_key)
    else:
        model = ScriptedModel(case)

    result = await diagnose(
        case["clinical_text"],
        models=Models(reasoner=model),
        tools=Tools(
            phenotype_extractor=GivenPhenotypes(case),
            expert_methods=[
                FileExpert("phenotype-ranker", case["case_id"]),
                FileExpert("case-matcher", case["case_id"]),
            ],
            knowledge_sources=[FileKnowledge()],
            case_indices=[FileCases()],
        ),
        config=Config(k=3),
    )

    top = result.top_k[0] if result.top_k else "(none)"
    hit = matches(top, case)
    print(f"\n  {case['case_id']}  [{case['input_type']}, {case['language']}]")
    print(f"    reference : {case['gold_diagnosis']}")
    print(f"    top-1     : {top}   {'match' if hit else 'no match'}")
    print(f"    ranked    : {', '.join(result.top_k)}")
    print(
        f"    evidence  : {len(result.evidence)} records over "
        f"{len(result.cycles)} round(s), settled={result.consistency_met}"
    )
    return hit


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="run one case id, e.g. case_003")
    ap.add_argument("--base-url", help="OpenAI-compatible endpoint")
    ap.add_argument("--model", default="", help="model id as the server lists it")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.base_url and not args.model:
        ap.error("--model is required with --base-url")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="  %(message)s",
    )

    paths = sorted((DATA / "cases").glob("*.json"))
    if args.case:
        paths = [
            p
            for p in paths
            if json.loads(p.read_text("utf-8"))["case_id"] == args.case
        ]
        if not paths:
            ap.error(f"no case with id {args.case}")

    hits = [await run_case(p, args) for p in paths]
    print(f"\n  top-1 match: {sum(hits)}/{len(hits)}")
    if not args.base_url:
        print("  (scripted model — pass --base-url and --model to use a real one)")


if __name__ == "__main__":
    asyncio.run(main())
