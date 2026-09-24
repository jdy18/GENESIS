# GENESIS data and knowledge resources

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
| RareArena | Approximately 50,000 cases; more than 4,000 diseases | Rare-disease clinical presentations supporting trajectory construction and case analogy. |
| [PMC-Patients](https://github.com/pmc-patients/pmc-patients) | 167,035 patient descriptions | Patient descriptions extracted from PubMed Central case reports; supports local case and literature retrieval. |

Case retrieval can use phenotype terms, clinical narrative representations and candidate disease names. Retrieved cases contribute supporting or discordant findings to the candidate-specific evidence record.

## Diagnostic tools and auxiliary models

| Component | Model or service | Role |
| --- | --- | --- |
| Phenotype-based diagnostic model | PhenoBrain | Ranks rare-disease candidates from a standardised phenotype set. |
| Phenotype-to-case service | PubCaseFinder | Supplies phenotype-based disease rankings against Orphanet and OMIM targets. |
| Biomedical concept encoder | BioLORD-2023 | Maps phenotype and disease names to ontology concepts through dense retrieval. |
| Case relevance model | MedCPT-Cross-Encoder | Scores the relevance of retrieved cases to the query case. |
| Auxiliary language model | Qwen3-8B | Extracts phenotypes, assesses record relevance and condenses retrieved material. |
| Embedding model | Qwen3-Embedding-8B | Produces dense representations for knowledge and case retrieval. |

These components connect through the repository's tool interfaces. Their responsibilities are independent of the orchestration code, allowing locally hosted services and indices to be connected through the same interfaces.

## Access and attribution

The repository distributes workflow code, prompts and original illustrative cases. Ontologies, model weights, literature and clinical corpora retain their source licences and access conditions. OMIM and MIMIC-IV are accessed under their respective agreements; resource users obtain those materials from their providers.

See [Training](model_training.md) for the derived training collections and [Inference](inference.md) for how evidence is used.
