import json
import unittest

from genesis import Config, Models, Tools, diagnose
from genesis.llm.openai_compat import OpenAIChat
from genesis.prompts import INITIAL_DIFFERENTIAL, KNOWLEDGE_QUERIES, EVIDENCE_FUSION
from genesis.tools import ConfiguredTool, ModelEvidenceSummarizer, ModelPhenotypeExtractor


class LocalModel:
    requires_external_access = False

    def __init__(self):
        self.calls = []

    async def chat(self, system, user, **kwargs):
        self.calls.append(system)
        return json.dumps({
            INITIAL_DIFFERENTIAL: {"candidates": [{"name": "Condition A", "rank": 1}]},
            KNOWLEDGE_QUERIES: {"defining_features": "Condition A findings"},
            EVIDENCE_FUSION: {
                "q1_diagnoses": [{"name": "Condition A", "confidence": "80%"}],
                "reflection_needed": False,
            },
        }[system])


class Source:
    name = "Source"

    def __init__(self):
        self.calls = 0

    async def search(self, query, top_k=3):
        self.calls += 1
        return [{"id": "K1", "text": "Condition A findings."}]


class MustNotRun:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def fail(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"blocked tool called: {name}")
        return fail


class NetworkSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_network_keeps_local_evidence_and_filters_all_tool_slots(self):
        local, external = Source(), Source()
        blocked_backend = MustNotRun()
        blocked = ConfiguredTool(blocked_backend, "External tool", True)
        tools = Tools(
            phenotype_extractor=blocked, concept_normalizer=blocked,
            expert_methods=[blocked], case_indices=[blocked], summarizer=blocked,
            knowledge_sources=[
                ConfiguredTool(local, "Local literature", False),
                ConfiguredTool(external, "PubMed", True),
            ],
        )
        result = await diagnose("Clinical case", Models(LocalModel()), tools,
                                Config(max_rounds=0, allow_external_requests=False))
        self.assertEqual(local.calls, 1)
        self.assertEqual(external.calls, 0)
        self.assertEqual(result.evidence[0].source, "Local literature (defining_features)")
        self.assertEqual(result.evidence[0].source_id, "K1")
        self.assertEqual(blocked_backend.calls, [])
        self.assertEqual(len(tools.knowledge_sources), 2)
        self.assertEqual(len(tools.expert_methods), 1)

    async def test_network_enabled_preserves_existing_unmarked_adapters(self):
        source = Source()
        await diagnose("Clinical case", Models(LocalModel()),
                       Tools(knowledge_sources=[source]), Config(max_rounds=0))
        self.assertEqual(source.calls, 1)

    async def test_source_switch_disables_tool_even_with_network_enabled(self):
        source = Source()
        await diagnose("Clinical case", Models(LocalModel()), Tools(knowledge_sources=[
            ConfiguredTool(source, "Wikipedia", True, enabled=False),
        ]), Config(max_rounds=0))
        self.assertEqual(source.calls, 0)

    async def test_unknown_tools_are_not_called_with_network_disabled(self):
        source = Source()
        result = await diagnose("Clinical case", Models(LocalModel()),
                                Tools(knowledge_sources=[source]),
                                Config(max_rounds=0, allow_external_requests=False))
        self.assertEqual(source.calls, 0)
        self.assertEqual(result.evidence, [])

    async def test_external_model_rejected_before_any_model_call(self):
        for role in ("reasoner", "auxiliary"):
            with self.subTest(role=role):
                reasoner, auxiliary = LocalModel(), LocalModel()
                target = reasoner if role == "reasoner" else auxiliary
                target.requires_external_access = True
                with self.assertRaisesRegex(ValueError, f"Models.{role}"):
                    await diagnose("Clinical case", Models(reasoner, auxiliary=auxiliary),
                                   config=Config(allow_external_requests=False))
                self.assertEqual(reasoner.calls + auxiliary.calls, [])

    async def test_unmarked_model_rejected_before_patient_extraction(self):
        class UndeclaredModel:
            async def chat(self, *args, **kwargs):
                raise AssertionError("model called")
        with self.assertRaisesRegex(ValueError, "Models.reasoner"):
            await diagnose("Clinical case", Models(UndeclaredModel()),
                           config=Config(allow_external_requests=False))

    def test_auxiliary_adapters_follow_their_model_access_declaration(self):
        model = OpenAIChat("http://localhost:8001/v1", "Qwen3-8B")
        for adapter in (ModelPhenotypeExtractor, ModelEvidenceSummarizer):
            self.assertTrue(adapter(model).requires_external_access)
        model.requires_external_access = False
        for adapter in (ModelPhenotypeExtractor, ModelEvidenceSummarizer):
            self.assertFalse(adapter(model).requires_external_access)

    def test_local_proxy_to_public_service_is_filtered(self):
        tool = ConfiguredTool(Source(), "PubCaseFinder via local MCP", True)
        self.assertEqual(Tools(expert_methods=[tool]).for_network(False).expert_methods, [])


if __name__ == "__main__":
    unittest.main()
