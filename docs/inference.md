# GENESIS inference methods

GENESIS organises diagnosis as an initial differential, three parallel evidence pathways, evidence fusion and, when required, audit-guided revision. The original clinical narrative remains available alongside structured findings throughout the workflow.

## Model roles

| Role | Responsibility |
| --- | --- |
| Reasoning model | Proposes candidate diagnoses and revises them after evidence review; GENESIS-R1 provides this role. |
| Working model | Interprets expert agreement, generates retrieval queries, compares disease entities, fuses evidence and articulates audit findings. |
| Auxiliary models | Extract phenotypes, normalise concepts, embed records and score retrieved cases through the tool layer. |

The `Models` interface separates `reasoner` from `worker`. A deployment can supply distinct models or use one model for both roles. Auxiliary models are connected through `Tools`.

## Initial differential

The reasoning model receives the clinical text, present findings, explicitly absent findings and the requested number of candidates. Each candidate records its rank, disease name, supporting findings, contradictory findings, unresolved questions and rationale. Explicit negative findings remain distinguishable from information that was not provided.

## Three evidence pathways

### Multi-expert consensus

Independent diagnostic methods return ranked disease lists. Concept normalisation consolidates labels for the same disease entity. Agreement is calculated from the presence and relative position of candidates in each list; the working model interprets the pattern and identifies credible alternatives outside the current differential.

### Dynamic knowledge retrieval and deduction

Candidate-specific queries address defining features, contradictory findings and disease mechanism. The initial retrieval budget uses one query per candidate and three records per source. Revision expands the budget to three queries and ten records per source. Evidence is attached to its candidate with source information and a supporting, refuting or neutral stance. The knowledge pathway is connected with both knowledge sources and an evidence summariser.

### Historical-case analogy

Case indices accept phenotype, narrative and candidate-name representations. A same-entity assessment checks whether a retrieved record corresponds to the candidate disease, accounting for synonyms and recognised subtypes. Relevant analogues supply shared findings, differences and source information. The retrieval budget controls the number of cases retained.

## Fusion and revision

Fusion reads the original case, the working differential, accumulated evidence and proposed alternatives. It produces a ranked differential with reasoning, workup suggestions and references, together with a signal indicating whether reflection is required. The clinical case is the primary source when it conflicts with retrieved or condensed material.

When reflection is requested, the audit combines candidate classification, cross-pathway support and the model's evidence review. The resulting report names unsupported claims, conflicting findings, evidence gaps and alternatives. The reasoning model receives the original case, its previous candidates, their accumulated evidence and the audit report. Candidates can be retained, removed, introduced or re-ranked before another evidence cycle.

The implementation treats `max_rounds` as the number of allowed revisions after the initial evidence cycle. For an initial cycle plus up to two revisions, use:

```python
config = Config(k=5, max_rounds=2)
```

The output contains `q1_diagnoses`, evidence cross-validation, source references and reflection status. Each diagnosis includes its name, rarity, model-reported confidence, rationale and suggested examinations. Cycle records retain the evidence and audit history.

## Local deployment

The orchestration package requires Python 3.10 or later and uses the Python standard library. Models are supplied through a `ChatModel` interface, with an OpenAI-compatible adapter provided. Knowledge indices, case collections and auxiliary services connect through the tool protocols. A local deployment hosts the model services and retrieval indices within the institution's computing environment; literature services can be attached according to the deployment's network policy.

```python
from genesis import Config, Models, Tools, diagnose
from genesis.llm.openai_compat import OpenAIChat

reasoner = OpenAIChat("http://localhost:8000/v1", "your-reasoning-model")
worker = OpenAIChat("http://localhost:8001/v1", "your-worker-model")
# Attach configured tool implementations through Tools(...).
config = Config(k=5, max_rounds=2)
```

The complete prompts are provided in [Prompts](prompts.md). Original, runnable illustrative inputs are in [`minimal_dataset`](../minimal_dataset/README.md).
