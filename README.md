# MedUnion-Agent

An evidence-auditing multi-agent diagnostic workflow: one model proposes a
differential, three agents examine it from independent angles, and an audit
decides whether the evidence has settled or another round is warranted.

This repository contains the orchestration layer. It depends only on the Python
standard library, and connects to your own models and retrieval indices through
seven small interfaces.

## Install

```bash
python3 -m pip install -e .          # nothing to fetch; stdlib only
python3 examples/minimal.py          # runs end to end against stubs
```

Python 3.10+.

## How it runs

```
                  free-text case
                        │
                        ▼
        ┌───────────────────────────────┐
        │ 1. propose a ranked           │   K candidates, each with supporting
        │    differential               │   and contradictory findings, open
        └───────────────┬───────────────┘   questions, and a rationale
                        │
   ┌────────────────────┤                     2. three pathways, in parallel
   │       ┌────────────┼─────────────┐
   │       ▼            ▼             ▼
   │  2.1 multi-    2.2 knowledge  2.3 similar
   │      expert        reasoning      cases
   │      consensus
   │      │             │              │
   │      └─────────────┼──────────────┘
   │                    ▼
   │    ┌───────────────────────────────┐
   │    │ 3. fuse the evidence into     │   the ranked answer, plus whether
   │    │    a ranked differential      │   the evidence settled the case
   │    └───────────────┬───────────────┘
   │                    │
   │               settled?
   │          ┌─────────┴─────────┐
   │         yes                  no
   │          │                   │
   │          ▼                   ▼
   │    final answer  ┌───────────────────────────────┐
   │                  │ 4. audit: name the            │
   │                  │    unsupported claims,        │
   │                  │    conflicts and gaps         │
   │                  └───────────────┬───────────────┘
   │                                  ▼
   │                  ┌───────────────────────────────┐
   │                  │ 5. revise the differential    │
   │                  │    against the audit          │
   │                  └───────────────┬───────────────┘
   │                                  │
   └──────────────────────────────────┘
        next round: greater retrieval depth, and only the newly
        introduced candidates are queried.  At most three rounds.
```

Steps 2 and 3 run every round, so the differential returned always reflects what
was retrieved. Steps 4 and 5 run only when fusion could not settle the case.

**2.1 Multi-expert consensus** asks whether the differential is reproducible
across independent diagnostic methods, and what those methods propose that the
differential omits. Agreement — presence and relative position in each ranked
list — is computed in code; the model is asked only to interpret it.

**2.2 Knowledge reasoning** queries the knowledge indices per candidate along
three axes: defining features, contradictory findings, mechanism. Retrieved
records are attached as evidence, passed through as retrieved by default.

**2.3 Similar cases** retrieves historical cases by phenotype set, narrative
embedding and candidate name, keeping only those judged to be the same disease
entity.

**3. Fusion** ranks the candidates against the evidence, anchored on the case
rather than on the retrieved records, and reports whether the evidence settled
the question. Its output is the answer the caller receives.

**4. Audit** classifies each candidate as *consensus*, *contested* or *emerged*,
and names what is unsupported, what conflicts, and what would have to be known to
separate the remaining candidates. That report is what step 5 revises against.

## Usage

```python
import asyncio
from medunion_agent import Config, Models, Tools, diagnose
from medunion_agent.llm.openai_compat import OpenAIChat

# reasoner: proposes the differential and revises it after each audit.
# worker:   drives the three agents' reasoning and the audit itself.
# They may be the same object; passing only `reasoner` uses it for both.
reasoner = OpenAIChat("http://localhost:8000/v1", "your-reasoning-model")
worker   = OpenAIChat("http://localhost:8001/v1", "your-worker-model",
                      thinking=False)

result = asyncio.run(diagnose(
    case_text,
    models=Models(reasoner=reasoner, worker=worker),
    tools=Tools(...),                 # see below
    config=Config(k=5, max_rounds=3),
))

print(result.top_k)                   # ranked differential
print(result.consistency_met)         # did the audit settle?
for cycle in result.cycles:           # full provenance chain
    print(cycle.index, cycle.audit.evidence_gaps)
```

## Scope

This package is the orchestration: the workflow, the three agents, the audit, the
prompts, and the data structures they exchange.

Retrieval indices and model weights stay on your side of seven interfaces, so the
same workflow runs against whatever stack you have — ontology snapshots, a
literature index, a case corpus, a single JSON file:

| Protocol               | Supplies                                                    |
| ---------------------- | ----------------------------------------------------------- |
| `PhenotypeExtractor` | free text → normalized findings (keep pertinent negatives) |
| `ConceptNormalizer`  | disease name → ontology ids, so labels can be consolidated |
| `ExpertMethod`       | one independent ranked differential                         |
| `KnowledgeSource`    | one queryable knowledge index                               |
| `CaseIndex`          | historical-case retrieval                                   |
| `EvidenceSummarizer` | optional: condense a record instead of passing it through   |
| `ChatModel`          | `chat(system, user) -> str`                               |

Every one is optional except `ChatModel`. An absent tool disables its pathway
rather than raising, and the audit is told the pathway was unavailable — "no
evidence found" and "the retrieval broke" are different inputs to a diagnostic
decision and must not look alike.

`medunion_agent/llm/openai_compat.py` is a worked binding of `ChatModel` to any
OpenAI-compatible server. `examples/minimal.py` implements all six tool protocols
as in-memory stubs, which is the shortest way to see what each one has to return.

## Running it

`examples/minimal.py` runs the whole workflow against in-memory stubs, so you can
see the control flow — proposal, three pathways, audit, revision — without any
services running.

To run it on real cases, supply:

1. **A model** behind `ChatModel`. `llm/openai_compat.py` works with any
   OpenAI-compatible server (vLLM, SGLang, Ollama, most gateways). One model is
   enough; two lets you put a larger one on the differential and a smaller one on
   the agents.
2. **At least one retrieval tool.** Each pathway activates when its tool is
   present, so you can start with one knowledge index and add the rest later.
   The stubs in `examples/minimal.py` show the shape each protocol returns.

Evaluation scripts are released separately.


## Licence

Apache 2.0
