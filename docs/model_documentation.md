# GENESIS model documentation

English | [简体中文](zh-CN/model_documentation.md)

## Model and training

GENESIS is the complete multi-agent diagnostic system. GENESIS-R1 is the trained medical reasoning model used within GENESIS. GENESIS combines three complementary evidence pathways with iterative evidence review. GENESIS-R1 performs Initial differential diagnosis, diagnostic reasoning across Multi-expert consensus, Dynamic knowledge retrieval and deduction, and Historical-case analogy, followed by Evidence fusion and, when required, Evidence-consistency audit and Revised differential diagnosis. Auxiliary models process findings and retrieved records; embedding models support retrieval.

### Model architecture

GENESIS-R1 is a specialised medical diagnostic reasoning model trained through supervised fine-tuning (SFT) on medical knowledge and diagnostic chains of thought, followed by reinforcement learning (RL) on diagnosis tasks. Training first develops general clinical reasoning and then extends this foundation to rare-disease knowledge and diagnostic reasoning. Knowledge question–answer pairs support disease understanding, while diagnostic chains of thought teach the model to connect clinical findings, compare diagnostic hypotheses and revise its reasoning.

The model is initialised from Qwen3-14B, an approximately 14-billion-parameter language model.

![GENESIS-R1 training: general medicine SFT, rare disease SFT and diagnosis-task RL with DAPO](figures/genesis-training.png)

### Inference model allocation

GENESIS-R1 is the reasoning model used for Initial differential diagnosis, diagnostic reasoning across the three evidence pathways, Evidence fusion, Evidence-consistency audit and Revised differential diagnosis. Final diagnosis is the final result returned after the last completed cycle; it does not require a separate model call.

The auxiliary language model is a smaller model used for fast processing of simpler supporting tasks: extracting clinical findings for HPO mapping, checking the relevance of retrieved material to candidate diagnoses, and extracting useful passages from long retrieved documents. We use Qwen3-8B for these tasks.

Qwen3-Embedding-8B is a separate embedding model that produces vector representations for retrieval. BioLORD-2023 maps clinical terms to ontology concepts, and MedCPT-Cross-Encoder scores retrieval relevance.

### Training datasets

Counts below describe the training-resource composition reported in the manuscript. The unit is a question–answer pair, a diagnostic chain of thought or a case-based RL prompt, as specified for each resource.

| Resource | Records | Unit | Training role |
| --- | ---: | --- | --- |
| GeneralKnowledge | 102,563 | Knowledge question–answer pairs | General medicine SFT |
| GeneralCOT | 139,573 | Diagnostic chains of thought | General medicine SFT |
| RareKnowledge | 64,099 | Knowledge question–answer pairs | Rare disease SFT |
| RareCOT | 103,282 | Diagnostic chains of thought | Rare disease SFT |
| GenesisRL | 21,497 | Case-based diagnosis prompts | Diagnosis-task RL across general and rare diseases |
| RL validation | 100 | Held-out prompts | Validation |

#### General medicine resources

**GeneralKnowledge** covers clinical presentation, differential diagnosis, disease mechanisms, investigation selection and therapeutic decision-making. Sources include ICD-10 and MONDO; national clinical guidelines, expert consensus statements and care pathways; antimicrobial prescribing principles and drug references; PubTator; PrimeKG and Monarch; and the MIMIC-IV and PMC-Patients case corpora.

**GeneralCOT** contains diagnostic chains of thought constructed from MIMIC-IV and PMC-Patients. Free-text cases are presented with different amounts of clinical information to support reasoning from both complete and restricted case descriptions.

#### Rare disease resources

**RareKnowledge** represents rare-disease knowledge derived from HPO, Orphanet, OMIM, MONDO and MAxO as question–answer pairs.

**RareCOT** contains diagnostic chains of thought constructed from RareArena cases outside the evaluation split. These chains of thought describe hypothesis generation, evidence assessment and diagnostic revision. To increase input diversity and construct diagnosis tasks of different difficulty, the same case is presented either as a clinical narrative or as standardised phenotype terms. The amount of available information is also varied: some inputs retain the full case description, while others omit selected clinical details. This trains the model to reason across different input formats and with different amounts of diagnostic evidence.

#### Reinforcement learning resources

**GenesisRL** is a diagnosis-task reinforcement-learning collection containing 21,497 case-based prompts. The clinical cases come from the MIMIC-IV, PMC-Patients and RareArena collections described above, covering general medicine and rare diseases. The model learns to derive diagnostic conclusions from the supplied clinical information. Training combines hard and extreme cases in a shared curriculum, with 100 additional prompts reserved for validation.

The RL stage uses DAPO to optimise diagnostic reasoning on these case-based tasks, building on the training approach described in [our prior work, RareDxR1](https://arxiv.org/abs/2607.00147) (Section III-E). A shared reward framework is used across general and rare diseases.

The reward design includes five components:

- **Accuracy Reward:** rewards agreement between the diagnostic answer and the reference diagnosis.
- **Answer Format:** encourages compliance with the required answer format.
- **Language Consistency:** encourages consistent language use throughout the response.
- **Non-Repetitive:** discourages redundant or repeated text.
- **Overlength Penalty:** penalises responses that exceed the configured length limit.

### From training to inference

Knowledge question–answer pairs support disease understanding, diagnostic chains of thought teach hypothesis evaluation, and RL refines the diagnostic reasoning process. At inference, GENESIS-R1 supplies a ranked candidate set to the multi-agent workflow. Retrieved evidence remains associated with the candidate it supports or challenges, and an audit can return the case for revision.

## Synthetic data construction

### Knowledge question–answer pairs

Structured ontology records, disease descriptions and clinical reference materials were organised into knowledge question–answer items. General-medicine items cover clinical presentation, disease mechanisms, differential diagnosis, investigations and management. Rare-disease items draw on HPO, Orphanet, OMIM, MONDO and MAxO.

### Diagnostic chains of thought

Diagnostic chains of thought are collected using Reflection-Enhanced Reasoning Sampling (RERS), described in [our prior work, RareDxR1](https://arxiv.org/abs/2607.00147) (Section III-D). This extends rejection sampling by reusing initially unsuccessful generations: the teacher model revisits its failed reasoning using retrieved knowledge and feedback from other diagnostic models, then generates a corrected chain of thought. The resulting reasoning is checked for diagnostic correctness and factual consistency before inclusion in the training data.

To increase input diversity and construct diagnosis tasks of different difficulty, the same case is presented either as a clinical narrative or as standardised phenotype terms. The amount of available information is also varied: some inputs retain the full case description, while others omit selected clinical details. This trains the model to reason across different input formats and with different amounts of diagnostic evidence. Partial-information inputs are created by randomly masking portions of the clinical narrative.

### Reinforcement learning prompts

Clinical cases from MIMIC-IV, PMC-Patients and RareArena were converted into diagnosis-task prompts for GenesisRL. The collection contains 21,497 training prompts spanning hard and extreme difficulty levels, with 100 additional prompts reserved for validation.

## Quality review criteria

Training-item review assessed agreement between the diagnostic conclusion and the reference diagnosis, together with factual consistency of the diagnostic chain of thought against the knowledge associated with that diagnosis. Reflection-based revision supplied corrected reasoning paths when the initial generation did not reach the reference diagnosis.

For record-derived training items, diagnosis-bearing input fields were removed, and reference diagnoses were obtained from structured coding. The data-construction description specifies removal of discharge-diagnosis, admission-diagnosis and chief-complaint fields. Cases belonging to evaluation sets were excluded before construction.

## Licences and access

The GENESIS code and original repository examples are distributed under the Apache License 2.0. Training sources, model weights, ontologies and clinical corpora remain subject to their own licences and access agreements. OMIM is accessed under its licensing terms, and MIMIC-IV under its credentialed data-use agreement. Literature-derived records retain the access and reuse conditions of their source publications. Model and embedding weights are obtained under the respective providers' model licences.

The resource inventory below separates an upstream release identifier from a collection date and specifies the intended role of each resource.

## Data and knowledge resources

Resources are organised by their role in model development and inference. A resource release identifies the upstream content version; a local snapshot date identifies when that content was collected. Corpus sizes refer to indexed resources, not evaluation sample sizes.

### Ontologies and knowledge bases

The resource inventory records a local collection snapshot of 25 August 2025. Individual ontology release identifiers are listed separately below.

| Resource | Version or snapshot | Content and role |
| --- | --- | --- |
| [HPO](https://hpo.jax.org/) | 2025-05-06 | 19,650 terms; phenotype hierarchy, synonyms and definitions. A 17,232-term definition-bearing subset supports concept normalisation. |
| [OMIM](https://www.omim.org/) | Local snapshot, 2025-08-25 | Disease entries, Clinical Synopsis, genes, phenotype mappings and linked publications; locally licensed access. |
| [Orphanet](https://www.orphadata.com/) | ORDO 4.6; HOOM 2.3; associated nomenclature pack | Rare-disease names, classification, gene associations and phenotypes; more than 6,000 rare diseases. |
| [MONDO](https://mondo.monarchinitiative.org/) | 2025-06-03 | Disease identifiers, synonyms and cross-resource mappings; supports terminology reconciliation. |
| [MAxO](https://github.com/monarch-initiative/MAxO) | 2025-04-24 | Medical actions and disease–phenotype annotations for diagnostic and management knowledge. |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | Training literature through May 2025 | Biomedical literature for training-resource construction and candidate-specific literature evidence. Online retrieval uses NCBI E-utilities. |

### Case repositories

| Resource | Inventory | Representation and use |
| --- | --- | --- |
| [MIMIC-IV](https://physionet.org/content/mimiciv/) | Locally indexed clinical records | Case narratives and phenotype profiles; disease labels reconciled with Orphanet. Access follows the source data-use agreement. |
| RareArena | Approximately 50,000 cases; more than 4,000 diseases | Rare-disease clinical presentations supporting diagnostic chain-of-thought collection and case analogy. |
| [PMC-Patients](https://github.com/pmc-patients/pmc-patients) | 167,035 patient descriptions | Patient descriptions extracted from PubMed Central case reports; supports local case and literature retrieval. |

Case retrieval can use phenotype terms, clinical narrative representations and candidate disease names. Retrieved cases contribute supporting or discordant findings to the candidate-specific evidence record.

### Diagnostic tools and auxiliary models

GENESIS is the complete multi-agent diagnostic system. GENESIS-R1 is the trained medical reasoning model used within GENESIS. The smaller auxiliary language model handles simpler supporting tasks quickly; we use Qwen3-8B. Qwen3-Embedding-8B provides the separate embedding model for retrieval.

| Component | Model or service | Role |
| --- | --- | --- |
| Diagnostic reasoning model | GENESIS-R1 | Performs candidate generation, evidence interpretation, independent case-analogy assessment, fusion, audit and revision. |
| Phenotype-based diagnostic model | PhenoBrain | Ranks rare-disease candidates from a standardised phenotype set. |
| Phenotype-to-case service | PubCaseFinder | Supplies phenotype-based disease rankings against Orphanet and OMIM targets. |
| Biomedical concept encoder | BioLORD-2023 | Maps phenotype and disease names to ontology concepts through dense retrieval. |
| Case relevance model | MedCPT-Cross-Encoder | Scores the relevance of retrieved cases to the query case. |
| Auxiliary language model | Qwen3-8B | Extracts findings for HPO mapping, checks retrieved material against candidate diagnoses and extracts useful passages from long documents. |
| Embedding model | Qwen3-Embedding-8B | Produces dense representations for knowledge and case retrieval. |

These components connect through the repository's tool interfaces. Their responsibilities are independent of the orchestration code, allowing locally hosted services and indices to be connected through the same interfaces.

### External retrieval tools and services

In addition to local knowledge and case indices, GENESIS can use external retrieval services when network access is enabled. PubMed provides biomedical literature through NCBI E-utilities; Wikipedia and general web search provide supplementary information with identifiable sources. PhenoBrain and PubCaseFinder supply phenotype-based disease rankings to Multi-expert consensus. Tool availability and access endpoints are determined by the deployment configuration.

General web search uses the engine provided by the configured adapter. Retrieved records retain source labels and available publication identifiers or URLs. PhenoBrain and PubCaseFinder are diagnostic tools rather than knowledge corpora. Public PubCaseFinder, live PubMed, Wikipedia and public search engines require external access, including when reached through a local MCP server. A locally deployed diagnostic service is available without external access only when its backend and required data are also local.

Crossref and MedlinePlus are not part of the default source configuration. Network and individual source switches are described in [Inference](inference.md#network-access-and-source-configuration).

### Access and attribution

The repository distributes workflow code, prompts and original illustrative cases. Ontologies, model weights, literature and clinical corpora retain their source licences and access conditions. OMIM and MIMIC-IV are accessed under their respective agreements; resource users obtain those materials from their providers.

## Multi-agent organisation and inference

GENESIS is the complete multi-agent diagnostic system. GENESIS-R1 is the trained medical reasoning model used within GENESIS.

GENESIS starts with Initial differential diagnosis, evaluates candidates through three parallel evidence pathways, and performs Evidence fusion. When further review is required, Evidence-consistency audit guides Revised differential diagnosis and a subsequent evidence cycle. The original clinical narrative remains available throughout.

### Model roles

GENESIS-R1 is the reasoning model used for Initial differential diagnosis, diagnostic reasoning across the three evidence pathways, Evidence fusion, Evidence-consistency audit and Revised differential diagnosis. Final diagnosis is the final result returned after the last completed cycle; it does not require a separate model call.

The auxiliary language model is a smaller model used for fast processing of simpler supporting tasks: extracting clinical findings for HPO mapping, checking the relevance of retrieved material to candidate diagnoses, and extracting useful passages from long retrieved documents. We use Qwen3-8B for these tasks.

Qwen3-Embedding-8B is a separate embedding model that produces vector representations for retrieval. BioLORD-2023 maps clinical terms to ontology concepts, and MedCPT-Cross-Encoder scores retrieval relevance.

### Initial differential diagnosis

GENESIS-R1 receives the clinical text, present findings, explicitly absent findings and requested number of candidates. It returns ranked candidates with disease names, supporting findings, contradictory findings, unresolved questions and rationales. Explicit negatives remain distinct from information that was not provided.

### Three evidence pathways

#### Multi-expert consensus

Independent diagnostic methods return ranked disease lists. Concept normalisation reconciles disease labels. Agreement is calculated from the presence and relative position of candidates in each list. GENESIS-R1 interprets this agreement and identifies credible alternatives outside the current differential. Its reply contains candidate assessments and alternatives; the pathway assembles these into evidence records.

#### Dynamic knowledge retrieval and deduction

GENESIS-R1 constructs candidate-specific queries for defining features, contradictory findings and disease mechanisms. The initial budget permits one query per candidate and three records per source. Revision permits three queries per candidate and ten records per source. The auxiliary model can extract relevant passages and assign an evidence stance; GENESIS-R1 weighs this material during Evidence fusion.

Knowledge retrieval runs whenever knowledge sources are configured and the pathway is enabled. `Tools.summarizer` is optional. Without it, the original records are passed through with a neutral stance. With `ModelEvidenceSummarizer(auxiliary)`, relevant passages are extracted while the source identifier and original record remain available. If this processing fails, the original retrieved record is retained.

#### Historical-case analogy

Historical cases are retrieved using phenotype terms, the clinical narrative or candidate disease names, depending on the case index. Regardless of how a case was retrieved, the auxiliary model compares its reported diagnosis with a current candidate diagnosis, allowing for synonymous names and recognised subtypes. Matching disease names alone does not establish clinical similarity or diagnose the current patient.

GENESIS-R1 independently compares the current patient’s symptoms, examination findings and disease course with those of the retrieved cases. It explains which similarities or differences support or argue against each candidate diagnosis and what remains uncertain. It may suggest additional diagnoses documented in the retrieved cases when the current patient’s findings justify considering them. Cases with diagnoses outside the current candidate list remain available for this comparison.

The comparison and the cited case records are passed to Evidence fusion, retaining the database name and available case or publication identifiers so that the evidence can be traced to its source.

If no cases are retrieved, this pathway has no historical-case evidence to contribute. If the GENESIS-R1 comparison is unavailable, records whose reported diagnoses match a candidate can still be passed on, without treating the name match as supporting clinical evidence.

### Evidence fusion

GENESIS-R1 reads the original case, working differential, accumulated evidence and proposed alternatives. It returns a ranked differential, diagnostic reasoning, suggested examinations, source references and a reflection flag. The clinical case is the primary source when it conflicts with retrieved material.

### Evidence-consistency audit and Revised differential diagnosis

If Evidence fusion requests reflection, the audit combines candidate classification, cross-pathway support and GENESIS-R1's evidence review. The report names unsupported claims, conflicting findings, evidence gaps and alternatives. GENESIS-R1 then receives the original case, previous candidates, accumulated evidence and audit findings to retain, remove, introduce or re-rank candidates before another evidence cycle.

`max_rounds` counts revisions after the initial evidence cycle. The default `max_rounds=3` allows one initial cycle plus at most three revisions: up to four evidence-and-fusion cycles in total. A case may stop earlier when the consistency criterion is met. For at most three total cycles, set `max_rounds=2`.

Setting `use_reflection=False` skips audit and revision. The returned result still reports whether Evidence fusion requested further review; disabling reflection does not itself satisfy the consistency criterion.

### Final diagnosis

Final diagnosis presents the ranked differential, diagnostic reasoning, recommended examinations and evidence sources from the last completed cycle. The final ranking is produced during Evidence fusion; presenting it does not require an additional model call.

### Local deployment

The package requires Python 3.10 or later and uses the standard library. The following wiring assigns all diagnostic model calls to GENESIS-R1 and auxiliary processing to Qwen3-8B. Models are hosted by the deployment; use the model identifiers advertised by its endpoints.

```python
from genesis import Config, Models, Tools, diagnose
from genesis.llm.openai_compat import OpenAIChat
from genesis.tools import ModelPhenotypeExtractor, ModelEvidenceSummarizer

reasoner = OpenAIChat("http://localhost:8000/v1", "GENESIS-R1")
auxiliary = OpenAIChat("http://localhost:8001/v1", "Qwen3-8B", thinking=False)
models = Models(reasoner=reasoner, auxiliary=auxiliary)
tools = Tools(
    phenotype_extractor=ModelPhenotypeExtractor(auxiliary),
    summarizer=ModelEvidenceSummarizer(auxiliary),
    # Attach expert_methods, knowledge_sources and case_indices here.
    # Configure embedding and ontology encoders in those tool implementations.
)
config = Config(k=5, max_rounds=3)
```

The phenotype adapter emits findings, explicit negatives and source spans; HPO identifiers are assigned by a configured ontology-mapping tool. The auxiliary model extracts textual findings rather than generating ontology identifiers.

For a minimal setup without a separate auxiliary endpoint, the same-entity check uses `reasoner`; extraction and passage processing remain optional tools. The `worker` constructor argument is a compatibility alias for the same `reasoner` object. A distinct model must be passed as `auxiliary`, not as `worker`.


### Network access and source configuration

Network access and individual sources can be configured separately. See [Inference](inference.md#network-access-and-source-configuration) for configuration parameters, local deployment examples and service access declarations.
