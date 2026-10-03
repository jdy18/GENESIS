# GENESIS data and knowledge resources

English | [简体中文](zh-CN/resources.md)

Resources are organised by their role in model development and inference. A resource release identifies the upstream content version; a local snapshot date identifies when that content was collected. Corpus sizes refer to indexed resources, not evaluation sample sizes.

## Ontologies and knowledge bases

The resource inventory records a local collection snapshot of 25 August 2025. Individual ontology release identifiers are listed separately below.

| Resource | Version or snapshot | Content and role |
| --- | --- | --- |
| [HPO](https://hpo.jax.org/) | 2025-05-06 | 19,650 terms; phenotype hierarchy, synonyms and definitions. A 17,232-term definition-bearing subset supports concept normalisation. |
| [OMIM](https://www.omim.org/) | Local snapshot, 2025-08-25 | Disease entries, Clinical Synopsis, genes, phenotype mappings and linked publications; locally licensed access. |
| [Orphanet](https://www.orphadata.com/) | ORDO 4.6; HOOM 2.3; associated nomenclature pack | Rare-disease names, classification, gene associations and phenotypes; more than 6,000 rare diseases. |
| [MONDO](https://mondo.monarchinitiative.org/) | 2025-06-03 | Disease identifiers, synonyms and cross-resource mappings; supports terminology reconciliation. |
| [MAxO](https://github.com/monarch-initiative/MAxO) | 2025-04-24 | Medical actions and disease–phenotype annotations for diagnostic and management knowledge. |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | Training literature through May 2025 | Biomedical literature for training-resource construction and candidate-specific literature evidence. Online retrieval uses NCBI E-utilities. |

## Case repositories

| Resource | Inventory | Representation and use |
| --- | --- | --- |
| [MIMIC-IV](https://physionet.org/content/mimiciv/) | Locally indexed clinical records | Case narratives and phenotype profiles; disease labels reconciled with Orphanet. Access follows the source data-use agreement. |
| RareArena | Approximately 50,000 cases; more than 4,000 diseases | Rare-disease clinical presentations supporting diagnostic chain-of-thought collection and case analogy. |
| [PMC-Patients](https://github.com/pmc-patients/pmc-patients) | 167,035 patient descriptions | Patient descriptions extracted from PubMed Central case reports; supports local case and literature retrieval. |

Case retrieval can use phenotype terms, clinical narrative representations and candidate disease names. Retrieved cases contribute supporting or discordant findings to the candidate-specific evidence record.

## Diagnostic tools and auxiliary models

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

## External retrieval tools and services

In addition to local knowledge and case indices, GENESIS can use external retrieval services when network access is enabled. PubMed provides biomedical literature through NCBI E-utilities; Wikipedia and general web search provide supplementary information with identifiable sources. PhenoBrain and PubCaseFinder supply phenotype-based disease rankings to Multi-expert consensus. Tool availability and access endpoints are determined by the deployment configuration.

General web search uses the engine provided by the configured adapter. Retrieved records retain source labels and available publication identifiers or URLs. PhenoBrain and PubCaseFinder are diagnostic tools rather than knowledge corpora. Public PubCaseFinder, live PubMed, Wikipedia and public search engines require external access, including when reached through a local MCP server. A locally deployed diagnostic service is available without external access only when its backend and required data are also local.

Crossref and MedlinePlus are not part of the default source configuration. Network and individual source switches are described in [Inference](inference.md#network-access-and-source-configuration).

## Access and attribution

The repository distributes workflow code, prompts and original illustrative cases. Ontologies, model weights, literature and clinical corpora retain their source licences and access conditions. OMIM and MIMIC-IV are accessed under their respective agreements; resource users obtain those materials from their providers.

See [Training](model_training.md) for the derived training collections and [Inference](inference.md) for how evidence is used.
