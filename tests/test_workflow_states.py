import json
import unittest

from genesis import Config, Models, diagnose
from genesis.prompts import (
    AUDIT_FINDINGS,
    EVIDENCE_FUSION,
    INITIAL_DIFFERENTIAL,
    REVISED_DIFFERENTIAL,
)


class Model:
    def __init__(self, reflection_needed):
        self.reflection_needed = reflection_needed
        self.calls = []

    async def chat(self, system, user, **kwargs):
        self.calls.append(system)
        if system in (INITIAL_DIFFERENTIAL, REVISED_DIFFERENTIAL):
            return json.dumps({"candidates": [{"name": "Condition A", "rank": 1}]})
        if system == EVIDENCE_FUSION:
            return json.dumps({
                "q1_diagnoses": [{"name": "Condition A"}],
                "reflection_needed": self.reflection_needed,
                "reflection_reason": "Further evidence is needed." if self.reflection_needed else "",
            })
        if system == AUDIT_FINDINGS:
            return json.dumps({"evidence_gaps": ["Diagnostic testing is unresolved."]})
        raise AssertionError("Unexpected model call")


class WorkflowStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabling_reflection_preserves_fusion_status_and_reason(self):
        for needed in (True, False):
            with self.subTest(reflection_needed=needed):
                model = Model(needed)
                result = await diagnose("Clinical case", Models(model),
                                        config=Config(use_reflection=False))
                self.assertEqual(model.calls, [INITIAL_DIFFERENTIAL, EVIDENCE_FUSION])
                self.assertEqual(result.consistency_met, not needed)
                self.assertEqual(result.cycles[-1].audit.consistent, not needed)
                self.assertEqual(result.to_dict()["reflection_needed"], needed)
                self.assertEqual(result.to_dict()["reflection_reason"],
                                 "Further evidence is needed." if needed else "")

    async def test_revision_limit_keeps_unresolved_status(self):
        for revisions in (0, 2):
            with self.subTest(max_rounds=revisions):
                model = Model(True)
                result = await diagnose("Clinical case", Models(model),
                                        config=Config(max_rounds=revisions))
                self.assertEqual(len(result.cycles), revisions + 1)
                self.assertEqual(model.calls.count(REVISED_DIFFERENTIAL), revisions)
                self.assertEqual(model.calls.count(AUDIT_FINDINGS), revisions + 1)
                self.assertFalse(result.consistency_met)
                self.assertTrue(result.to_dict()["reflection_needed"])
                self.assertEqual(result.to_dict()["reflection_reason"],
                                 "Diagnostic testing is unresolved.")

    async def test_settled_fusion_skips_audit_and_revision(self):
        model = Model(False)
        result = await diagnose("Clinical case", Models(model))
        self.assertEqual(model.calls, [INITIAL_DIFFERENTIAL, EVIDENCE_FUSION])
        self.assertTrue(result.consistency_met)
        self.assertEqual(len(result.cycles), 1)
        self.assertFalse(result.to_dict()["reflection_needed"])


if __name__ == "__main__":
    unittest.main()
