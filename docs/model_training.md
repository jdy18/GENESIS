# GENESIS model and training

English | [简体中文](zh-CN/model_training.md)

GENESIS is the complete multi-agent diagnostic system. GENESIS-R1 is the trained medical reasoning model used within GENESIS. GENESIS combines three complementary evidence pathways with iterative evidence review. GENESIS-R1 performs Initial differential diagnosis, diagnostic reasoning across Multi-expert consensus, Dynamic knowledge retrieval and deduction, and Historical-case analogy, followed by Evidence fusion and, when required, Evidence-consistency audit and Revised differential diagnosis. Auxiliary models process findings and retrieved records; embedding models support retrieval.

## Model architecture

GENESIS-R1 is a specialised medical diagnostic reasoning model trained through supervised fine-tuning (SFT) on medical knowledge and diagnostic chains of thought, followed by reinforcement learning (RL) on diagnosis tasks. Training first develops general clinical reasoning and then extends this foundation to rare-disease knowledge and diagnostic reasoning. Knowledge question–answer pairs support disease understanding, while diagnostic chains of thought teach the model to connect clinical findings, compare diagnostic hypotheses and revise its reasoning.

The model is initialised from Qwen3-14B, an approximately 14-billion-parameter language model.

![GENESIS-R1 training: general medicine SFT, rare disease SFT and diagnosis-task RL with DAPO](figures/genesis-training.png)

## Inference model allocation

GENESIS-R1 is the reasoning model used for Initial differential diagnosis, diagnostic reasoning across the three evidence pathways, Evidence fusion, Evidence-consistency audit and Revised differential diagnosis. Final diagnosis is the final result returned after the last completed cycle; it does not require a separate model call.

The auxiliary language model is a smaller model used for fast processing of simpler supporting tasks: extracting clinical findings for HPO mapping, checking the relevance of retrieved material to candidate diagnoses, and extracting useful passages from long retrieved documents. We use Qwen3-8B for these tasks.

Qwen3-Embedding-8B is a separate embedding model that produces vector representations for retrieval. BioLORD-2023 maps clinical terms to ontology concepts, and MedCPT-Cross-Encoder scores retrieval relevance.

## Training datasets

Counts below describe the training-resource composition reported in the manuscript. The unit is a question–answer pair, a diagnostic chain of thought or a case-based RL prompt, as specified for each resource.

| Resource | Records | Unit | Training role |
| --- | ---: | --- | --- |
| GeneralKnowledge | 102,563 | Knowledge question–answer pairs | General medicine SFT |
| GeneralCOT | 139,573 | Diagnostic chains of thought | General medicine SFT |
| RareKnowledge | 64,099 | Knowledge question–answer pairs | Rare disease SFT |
| RareCOT | 103,282 | Diagnostic chains of thought | Rare disease SFT |
| GenesisRL | 21,497 | Case-based diagnosis prompts | Diagnosis-task RL across general and rare diseases |
| RL validation | 100 | Held-out prompts | Validation |

### General medicine resources

**GeneralKnowledge** covers clinical presentation, differential diagnosis, disease mechanisms, investigation selection and therapeutic decision-making. Sources include ICD-10 and MONDO; national clinical guidelines, expert consensus statements and care pathways; antimicrobial prescribing principles and drug references; PubTator; PrimeKG and Monarch; and the MIMIC-IV and PMC-Patients case corpora.

**GeneralCOT** contains diagnostic chains of thought constructed from MIMIC-IV and PMC-Patients. Free-text cases are presented with different amounts of clinical information to support reasoning from both complete and restricted case descriptions.

### Rare disease resources

**RareKnowledge** represents rare-disease knowledge derived from HPO, Orphanet, OMIM, MONDO and MAxO as question–answer pairs.

**RareCOT** contains diagnostic chains of thought constructed from RareArena cases outside the evaluation split. These chains of thought describe hypothesis generation, evidence assessment and diagnostic revision. To increase input diversity and construct diagnosis tasks of different difficulty, the same case is presented either as a clinical narrative or as standardised phenotype terms. The amount of available information is also varied: some inputs retain the full case description, while others omit selected clinical details. This trains the model to reason across different input formats and with different amounts of diagnostic evidence.

### Diagnostic chain-of-thought collection

Diagnostic chains of thought are collected using Reflection-Enhanced Reasoning Sampling (RERS), described in [our prior work, RareDxR1](https://arxiv.org/abs/2607.00147) (Section III-D). This extends rejection sampling by reusing initially unsuccessful generations: the teacher model revisits its failed reasoning using retrieved knowledge and feedback from other diagnostic models, then generates a corrected chain of thought. The resulting reasoning is checked for diagnostic correctness and factual consistency before inclusion in the training data.

### Reinforcement learning resources

**GenesisRL** is a diagnosis-task reinforcement-learning collection containing 21,497 case-based prompts. The clinical cases come from the MIMIC-IV, PMC-Patients and RareArena collections described above, covering general medicine and rare diseases. The model learns to derive diagnostic conclusions from the supplied clinical information. Training combines hard and extreme cases in a shared curriculum, with 100 additional prompts reserved for validation.

The RL stage uses DAPO to optimise diagnostic reasoning on these case-based tasks, building on the training approach described in [our prior work, RareDxR1](https://arxiv.org/abs/2607.00147) (Section III-E). A shared reward framework is used across general and rare diseases.

The reward design includes five components:

- **Accuracy Reward:** rewards agreement between the diagnostic answer and the reference diagnosis.
- **Answer Format:** encourages compliance with the required answer format.
- **Language Consistency:** encourages consistent language use throughout the response.
- **Non-Repetitive:** discourages redundant or repeated text.
- **Overlength Penalty:** penalises responses that exceed the configured length limit.

## From training to inference

Knowledge question–answer pairs support disease understanding, diagnostic chains of thought teach hypothesis evaluation, and RL refines the diagnostic reasoning process. At inference, GENESIS-R1 supplies a ranked candidate set to the multi-agent workflow. Retrieved evidence remains associated with the candidate it supports or challenges, and an audit can return the case for revision.

See [Resources](resources.md) for the knowledge and case collections, [Inference](inference.md) for the workflow, and [Prompts](prompts.md) for the complete prompt templates.
