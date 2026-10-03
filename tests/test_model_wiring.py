import json
import unittest

from genesis import Candidate, Config, Models, Tools, diagnose
from genesis.agents.knowledge import run as retrieve
from genesis.prompts import ALL
from genesis.tools import ModelEvidenceSummarizer, ModelPhenotypeExtractor
from genesis.types import EvidenceKind


class Model:
    def __init__(self):
        self.calls = []

    async def chat(self, system, user, **kwargs):
        key = next(k for k, v in ALL.items() if v == system)
        self.calls.append(key)
        return json.dumps({
            'initial_differential': {'candidates': [{'name': 'Condition A', 'rank': 1}]},
            'consensus_synthesis': {'assessments': [], 'alternatives': []},
            'knowledge_queries': {'defining_features': 'Condition A findings'},
            'analogy_same_entity': {'same_entity': True, 'justification': 'Same entity.'},
            'analogy_synthesis': {'assessments': [{
                'candidate': 'Condition A', 'stance': 'supports',
                'summary': 'The historical case supports considering Condition A.',
                'sources': ['Case source — case C1'],
            }], 'alternatives': []},
            'evidence_fusion': {'q1_diagnoses': [{'name': 'Condition A'}], 'reflection_needed': True},
            'audit_findings': {'unsupported_claims': [], 'conflicting_findings': [], 'evidence_gaps': []},
            'record_condensation': {'summary': 'Relevant source passage.', 'stance': 'neutral'},
            'phenotype_extraction': {'findings': [
                {'name': 'Fever', 'present': False, 'source_span': 'No fever'},
                {'name': 'Unsupported finding', 'present': True, 'source_span': 'not in case'},
                {'name': 'Bad boolean', 'present': 'false', 'source_span': 'No fever'},
            ]},
        }[key])


class Knowledge:
    name = 'Knowledge source'
    async def search(self, query, top_k=3):
        return [{'id': 'K1', 'text': 'Relevant source passage.'}]


class Cases:
    name = 'Case source'
    async def search(self, *args, **kwargs):
        return [{'case_id': 'C1', 'diagnosis': 'Condition A'}]


class Expert:
    name = 'Expert method'
    async def rank(self, *args):
        return [Candidate('Condition A', 1)]


class WiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_diagnostic_and_auxiliary_calls_are_separate(self):
        reasoner, auxiliary = Model(), Model()
        result = await diagnose('No fever', Models(reasoner, auxiliary=auxiliary), Tools(
            phenotype_extractor=ModelPhenotypeExtractor(auxiliary),
            summarizer=ModelEvidenceSummarizer(auxiliary),
            expert_methods=[Expert()], knowledge_sources=[Knowledge()], case_indices=[Cases()],
        ), Config(max_rounds=0))
        self.assertEqual(set(reasoner.calls), {'initial_differential', 'consensus_synthesis',
                         'knowledge_queries', 'analogy_synthesis', 'evidence_fusion', 'audit_findings'})
        self.assertEqual(set(auxiliary.calls), {'phenotype_extraction', 'record_condensation',
                                              'analogy_same_entity'})
        self.assertEqual({e.kind for e in result.evidence}, set(EvidenceKind))

    async def test_knowledge_runs_without_summarizer(self):
        result = await diagnose('case', Models(Model()),
                                Tools(knowledge_sources=[Knowledge()]), Config(max_rounds=0))
        self.assertEqual(len(result.evidence), 1)
        ev = result.evidence[0]
        self.assertEqual(ev.source_id, 'K1')
        self.assertIn('Relevant source passage.', ev.content)
        self.assertEqual(ev.stance.value, 'neutral')

    async def test_failed_summarization_retains_original(self):
        class Broken:
            async def summarize(self, *args):
                raise RuntimeError('unavailable')
        report = await retrieve([Candidate('Condition A', 1)], [], [Knowledge()],
                                Model(), Broken())
        self.assertEqual(report.evidence[0].source_id, 'K1')
        self.assertIn('Relevant source passage.', report.evidence[0].content)
        self.assertIn('retained original', report.notes)

    async def test_extractor_keeps_explicit_negative_and_source(self):
        items = await ModelPhenotypeExtractor(Model()).extract('No fever')
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].present)
        self.assertEqual(items[0].source_span, 'No fever')
        self.assertIsNone(items[0].term_id)

    async def test_summarizer_keeps_source_record(self):
        rec = {'pmid': '123', 'text': 'Relevant source passage.', 'score': 0.8}
        ev = await ModelEvidenceSummarizer(Model()).summarize(
            Candidate('Condition A', 1), rec, EvidenceKind.KNOWLEDGE, 'PubMed')
        self.assertEqual(ev.source_id, '123')
        self.assertEqual(ev.raw, rec)
        self.assertEqual(ev.content, 'Relevant source passage.')

    def test_legacy_worker_must_be_same_reasoner(self):
        model = Model()
        self.assertIs(Models(model, worker=model).reasoner, model)
        with self.assertRaisesRegex(ValueError, 'auxiliary'):
            Models(Model(), worker=Model())


if __name__ == '__main__':
    unittest.main()
