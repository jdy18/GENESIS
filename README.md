# GENESIS

An evidence-auditing multi-agent diagnostic workflow: one model proposes a
differential, three agents examine it from independent angles, a fusion step
ranks the candidates against what was retrieved, and an audit decides whether
another round is warranted.

This repository is the orchestration layer. It depends only on the Python
standard library, and connects to your own models and retrieval indices through
seven small interfaces.

## How it runs

```text
                       free-text case
                             │
                             ▼
              ┌──────────────────────────────┐
              │ 1. propose a differential    │   K candidates, each with
              │                              │   supporting / contradictory
              └──────────────┬───────────────┘   findings, open questions,
                             │                   rationale
             ┌───────────────┼───────────────┐
             ▼               ▼               ▼   2. three pathways, in parallel
        2.1 multi-expert  2.2 knowledge  2.3 similar
            consensus         reasoning      cases
             │               │               │
             └───────────────┼───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │ 3. fusion → ranked answer    │   the differential the caller
              └──────────────┬───────────────┘   receives
                             │
                    settled? │
                   ┌─────────┴─────────┐
                  yes                 no ─── up to 3 rounds
                   │                   │
                   ▼                   ▼
            final answer      ┌──────────────────────────────┐
                              │ 4. audit → what is missing   │
                              └──────────────┬───────────────┘
                                             ▼
                              ┌──────────────────────────────┐
                              │ 5. revise the differential   │
                              └──────────────┬───────────────┘
                                             │
                                   back to 2 ┘
```

**1. Propose.** The reasoning model reads the case and returns a ranked
differential. Each candidate carries the findings that support it, the findings
that contradict it, the questions left open, and its rationale.

**2.1 Multi-expert consensus.** Asks whether the differential is reproducible
across independent diagnostic methods, and what those methods propose that the
differential omits. Agreement — presence and relative position in each ranked
list — is computed in code; the model is asked only to interpret it.

**2.2 Knowledge reasoning.** Queries the knowledge indices per candidate along
three axes: defining features, contradictory findings, mechanism. Retrieved
records are attached as evidence, passed through as retrieved by default.

**2.3 Similar cases.** Retrieves historical cases by phenotype set, narrative and
candidate name, keeping only those judged to be the same disease entity.

**3. Fusion.** Ranks the candidates against everything retrieved, and produces
the answer the caller receives. Runs every round, so the differential returned
always reflects the evidence rather than only the initial proposal.

**4. Audit.** Runs when fusion could not settle the case. Classifies each
candidate as *consensus*, *contested* or *emerged*, then names what is missing:
unsupported claims, conflicting findings, evidence gaps, proposed alternatives.

**5. Revise.** The reasoning model reworks the differential against the audit.
Newly introduced candidates go back through retrieval, at greater depth; the rest
already have evidence. At most three rounds.

Every stage receives the full case text, with retrieved evidence added alongside
it.

## Install

```bash
python3 -m pip install -e .        # nothing to fetch; stdlib only
```

Python 3.10+.

## Usage

Run the bundled dataset with no services running:

```bash
python3 examples/run_dataset.py
```

Then point it at a model:

```bash
python3 examples/run_dataset.py --base-url http://localhost:8000/v1 \
                                --model your-model
```

In code:

```python
import asyncio
from genesis import Config, Models, Tools, diagnose
from genesis.llm.openai_compat import OpenAIChat

# reasoner: proposes the differential and revises it after each audit.
# worker:   drives the three agents' reasoning, the fusion and the audit.
# They may be the same object; passing only `reasoner` uses it for both.
reasoner = OpenAIChat("http://localhost:8000/v1", "your-reasoning-model")
worker = OpenAIChat("http://localhost:8001/v1", "your-worker-model",
                    thinking=False)

result = asyncio.run(diagnose(
    case_text,
    models=Models(reasoner=reasoner, worker=worker),
    tools=Tools(...),               # see Interfaces
    config=Config(k=5, max_rounds=3),
))

result.top_k              # ranked differential
result.consistency_met    # did it settle?
result.to_dict()          # the answer in the q1_diagnoses schema
result.cycles             # candidates, evidence and audit for every round
```

## Interfaces

Retrieval indices and model weights stay on your side of seven protocols, so the
same workflow runs against whatever stack you have — ontology snapshots, a
literature index, a case corpus, a single JSON file:

| Protocol             | Supplies                                                     |
| -------------------- | ------------------------------------------------------------ |
| `ChatModel`          | `chat(system, user) -> str`                                  |
| `PhenotypeExtractor` | free text → normalized findings, keeping pertinent negatives |
| `ConceptNormalizer`  | disease name → ontology ids, so labels can be consolidated   |
| `ExpertMethod`       | one independent ranked differential                          |
| `KnowledgeSource`    | one queryable knowledge index                                |
| `CaseIndex`          | historical-case retrieval                                    |
| `EvidenceSummarizer` | optional: condense a record instead of passing it through    |

Every one is optional except `ChatModel`. A pathway activates when its tool is
present, so you can start with one knowledge index and add the rest later.

`examples/run_dataset.py` implements four of them against plain JSON files in
about eighty lines, which is the shortest way to see what each has to return.
`genesis/llm/openai_compat.py` is a worked `ChatModel` for any
OpenAI-compatible server: vLLM, SGLang, Ollama, most gateways.

## Dataset

`minimal_dataset/` holds three cases and three small indices, enough to exercise
the workflow end to end. The cases cover the input shapes it has to handle: an
English narrative with laboratory and histology detail, a pre-extracted phenotype
list with pertinent negatives, and a Chinese narrative whose decisive clues live
in the prose. See `minimal_dataset/README.md`.

## Layout

```text
genesis/
  workflow.py          orchestration, up to three rounds
  engine.py            proposes and revises the differential
  prompts.py           every prompt, in one place
  types.py             Candidate, Evidence, AuditReport, DiagnosisResult
  agents/
    consensus.py       2.1  agreement across independent methods
    knowledge.py       2.2  per-candidate retrieval, three axes
    analogy.py         2.3  historical cases, same-entity checked
    fusion.py          3    evidence → ranked answer
    audit.py           4    classification and consistency criterion
  tools/base.py        the six tool protocols
  llm/
    base.py            ChatModel protocol and JSON coercion
    openai_compat.py   binding for OpenAI-compatible servers
examples/
  minimal.py           control flow against in-memory stubs
  run_dataset.py       minimal_dataset with file-backed tools
minimal_dataset/
  cases/               three cases
  indices/             knowledge, historical cases, expert rankings
```

## Licence

Apache 2.0
