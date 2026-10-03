import json
import unittest

from genesis.agents.analogy import run
from genesis.agents.fusion import run as fuse
from genesis.prompts import ANALOGY_SAME_ENTITY, ANALOGY_SYNTHESIS, EVIDENCE_FUSION
from genesis.types import Candidate, Phenotype, Stance


class Cases:
    name = "Case database"

    async def search(self, *args):
        return [
            {"case_id": "C1", "diagnosis": "Condition A", "text": "Fever without rash."},
            {"case_id": "C2", "diagnosis": "Condition B", "text": "Recurrent fever."},
        ]


class Auxiliary:
    def __init__(self):
        self.calls = []

    async def chat(self, system, user, **kwargs):
        self.calls.append(system)
        assert system == ANALOGY_SAME_ENTITY
        data = json.loads(user)
        return json.dumps({"same_entity": data["retrieved_case"]["case_id"] == "C1",
                           "justification": "Comparison of the recorded diagnosis labels."})


class Reasoner:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "assessments": [{"candidate": "Condition A", "stance": "neutral",
                             "summary": "Fever overlaps, but the time course differs.",
                             "sources": ["Case database — case C1"]}],
            "alternatives": [{"name": "Condition B", "rationale": "Recurrent fever matches the historical course.",
                              "sources": ["Case database — case C2"]}],
        }

    async def chat(self, system, user, **kwargs):
        self.calls.append((system, json.loads(user)))
        if system == ANALOGY_SYNTHESIS:
            return self.response if isinstance(self.response, str) else json.dumps(self.response)
        if system == EVIDENCE_FUSION:
            return json.dumps({"q1_diagnoses": [{"name": "Condition B"}], "reflection_needed": False})
        raise AssertionError("Unexpected prompt")


class AnalogyTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_synthesis_reaches_fusion_with_original_sources(self):
        reasoner, auxiliary = Reasoner(), Auxiliary()
        candidates = [Candidate("Condition A", 1)]
        report = await run(candidates, [Phenotype("Rash", present=False)],
                           "Recurrent fever. No rash.", [Cases()], reasoner, auxiliary=auxiliary)
        self.assertEqual(len(reasoner.calls), 1)
        self.assertEqual(auxiliary.calls, [ANALOGY_SAME_ENTITY] * 2)
        payload = reasoner.calls[0][1]
        self.assertEqual(payload["clinical_case"], "Recurrent fever. No rash.")
        self.assertEqual(payload["findings_absent"], ["Rash"])
        self.assertEqual(len(payload["retrieved_cases"]), 2)
        # C2 did not match A, but remains available to support a new diagnosis.
        self.assertFalse(payload["same_entity_checks"][1]["same_entity"])
        self.assertEqual(report.synthesis, reasoner.response)
        self.assertEqual(report.new_candidates[0].name, "Condition B")
        self.assertEqual(report.evidence[0].stance, Stance.NEUTRAL)
        self.assertEqual(report.evidence[0].source_id, "C1")
        self.assertEqual(report.evidence[0].raw["record"]["text"], "Fever without rash.")
        await fuse(reasoner, "Recurrent fever. No rash.", [], candidates,
                   report.evidence, report.new_candidates)
        fusion_input = reasoner.calls[-1][1]
        evidence = fusion_input["working_differential"][0]["evidence"][0]
        self.assertIn("Fever without rash.", evidence["record"])
        self.assertIn("time course differs", evidence["summary"])
        alt = fusion_input["alternatives_proposed_by_agents"][0]
        self.assertEqual(alt["evidence"][0]["source_id"], "C2")

    async def test_unknown_sources_cannot_introduce_evidence_or_alternatives(self):
        response = {"assessments": [{"candidate": "Condition A", "stance": "supports",
                                    "summary": "Unsupported", "sources": ["invented"]}],
                    "alternatives": [{"name": "Condition X", "rationale": "Unsupported",
                                      "sources": ["invented"]}]}
        report = await run([Candidate("Condition A", 1)], [], "case", [Cases()],
                           Reasoner(response), auxiliary=Auxiliary())
        self.assertEqual(report.new_candidates, [])
        self.assertTrue(all(e.stance == Stance.NEUTRAL for e in report.evidence))
        self.assertTrue(all(e.source != "invented" for e in report.evidence))
        self.assertIn("unknown source", report.notes)

    async def test_failed_synthesis_keeps_matched_record_without_asserting_support(self):
        for response in ("invalid JSON", "{}", '{"assessments":{},"alternatives":[]}'):
            report = await run([Candidate("Condition A", 1)], [], "case", [Cases()],
                               Reasoner(response), auxiliary=Auxiliary())
            self.assertIsNone(report.synthesis)
            self.assertEqual(report.evidence[0].source_id, "C1")
            self.assertIn("Fever without rash.", report.evidence[0].content)
            self.assertEqual(report.evidence[0].stance, Stance.NEUTRAL)
            self.assertIn("synthesis:", report.notes)

    async def test_empty_retrieval_skips_synthesis(self):
        class Empty(Cases):
            async def search(self, *args):
                return []
        model = Reasoner()
        report = await run([Candidate("Condition A", 1)], [], "case", [Empty()], model)
        self.assertEqual(model.calls, [])
        self.assertIsNone(report.synthesis)
        self.assertEqual(report.evidence[0].stance, Stance.NEUTRAL)

    async def test_without_auxiliary_reasoner_handles_both_tasks(self):
        class Combined(Reasoner):
            async def chat(self, system, user, **kwargs):
                if system == ANALOGY_SAME_ENTITY:
                    return await Auxiliary().chat(system, user, **kwargs)
                return await super().chat(system, user, **kwargs)
        model = Combined()
        report = await run([Candidate("Condition A", 1)], [], "case", [Cases()], model)
        self.assertIsNotNone(report.synthesis)


if __name__ == "__main__":
    unittest.main()
