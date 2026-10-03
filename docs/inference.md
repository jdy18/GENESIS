# GENESIS inference methods

English | [简体中文](zh-CN/inference.md)

GENESIS is the complete multi-agent diagnostic system. GENESIS-R1 is the trained medical reasoning model used within GENESIS.

GENESIS starts with Initial differential diagnosis, evaluates candidates through three parallel evidence pathways, and performs Evidence fusion. When further review is required, Evidence-consistency audit guides Revised differential diagnosis and a subsequent evidence cycle. The original clinical narrative remains available throughout.

## Model roles

GENESIS-R1 is the reasoning model used for Initial differential diagnosis, diagnostic reasoning across the three evidence pathways, Evidence fusion, Evidence-consistency audit and Revised differential diagnosis. Final diagnosis is the final result returned after the last completed cycle; it does not require a separate model call.

The auxiliary language model is a smaller model used for fast processing of simpler supporting tasks: extracting clinical findings for HPO mapping, checking the relevance of retrieved material to candidate diagnoses, and extracting useful passages from long retrieved documents. We use Qwen3-8B for these tasks.

Qwen3-Embedding-8B is a separate embedding model that produces vector representations for retrieval. BioLORD-2023 maps clinical terms to ontology concepts, and MedCPT-Cross-Encoder scores retrieval relevance.

## Initial differential diagnosis

GENESIS-R1 receives the clinical text, present findings, explicitly absent findings and requested number of candidates. It returns ranked candidates with disease names, supporting findings, contradictory findings, unresolved questions and rationales. Explicit negatives remain distinct from information that was not provided.

## Three evidence pathways

### Multi-expert consensus

Independent diagnostic methods return ranked disease lists. Concept normalisation reconciles disease labels. Agreement is calculated from the presence and relative position of candidates in each list. GENESIS-R1 interprets this agreement and identifies credible alternatives outside the current differential. Its reply contains candidate assessments and alternatives; the pathway assembles these into evidence records.

### Dynamic knowledge retrieval and deduction

GENESIS-R1 constructs candidate-specific queries for defining features, contradictory findings and disease mechanisms. The initial budget permits one query per candidate and three records per source. Revision permits three queries per candidate and ten records per source. The auxiliary model can extract relevant passages and assign an evidence stance; GENESIS-R1 weighs this material during Evidence fusion.

Knowledge retrieval runs whenever knowledge sources are configured and the pathway is enabled. `Tools.summarizer` is optional. Without it, the original records are passed through with a neutral stance. With `ModelEvidenceSummarizer(auxiliary)`, relevant passages are extracted while the source identifier and original record remain available. If this processing fails, the original retrieved record is retained.

### Historical-case analogy

Historical cases are retrieved using phenotype terms, the clinical narrative or candidate disease names, depending on the case index. Regardless of how a case was retrieved, the auxiliary model compares its reported diagnosis with a current candidate diagnosis, allowing for synonymous names and recognised subtypes. Matching disease names alone does not establish clinical similarity or diagnose the current patient.

GENESIS-R1 independently compares the current patient’s symptoms, examination findings and disease course with those of the retrieved cases. It explains which similarities or differences support or argue against each candidate diagnosis and what remains uncertain. It may suggest additional diagnoses documented in the retrieved cases when the current patient’s findings justify considering them. Cases with diagnoses outside the current candidate list remain available for this comparison.

The comparison and the cited case records are passed to Evidence fusion, retaining the database name and available case or publication identifiers so that the evidence can be traced to its source.

If no cases are retrieved, this pathway has no historical-case evidence to contribute. If the GENESIS-R1 comparison is unavailable, records whose reported diagnoses match a candidate can still be passed on, without treating the name match as supporting clinical evidence.

## Evidence fusion

GENESIS-R1 reads the original case, working differential, accumulated evidence and proposed alternatives. It returns a ranked differential, diagnostic reasoning, suggested examinations, source references and a reflection flag. The clinical case is the primary source when it conflicts with retrieved material.

## Evidence-consistency audit and Revised differential diagnosis

If Evidence fusion requests reflection, the audit combines candidate classification, cross-pathway support and GENESIS-R1's evidence review. The report names unsupported claims, conflicting findings, evidence gaps and alternatives. GENESIS-R1 then receives the original case, previous candidates, accumulated evidence and audit findings to retain, remove, introduce or re-rank candidates before another evidence cycle.

`max_rounds` counts revisions after the initial evidence cycle. The default `max_rounds=3` allows one initial cycle plus at most three revisions: up to four evidence-and-fusion cycles in total. A case may stop earlier when the consistency criterion is met. For at most three total cycles, set `max_rounds=2`.

Setting `use_reflection=False` skips audit and revision. The returned result still reports whether Evidence fusion requested further review; disabling reflection does not itself satisfy the consistency criterion.

## Final diagnosis

Final diagnosis presents the ranked differential, diagnostic reasoning, recommended examinations and evidence sources from the last completed cycle. The final ranking is produced during Evidence fusion; presenting it does not require an additional model call.

## Local deployment

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

See [Prompts](prompts.md) for templates and [`minimal_dataset`](../minimal_dataset/README.md) for runnable illustrative inputs.

## Network access and source configuration

In the network-enabled setting, local evidence resources can be supplemented by configured external literature, knowledge and web-search services. Public PubCaseFinder access is enabled when required by the selected configuration.

In the network-disabled setting, external service requests are disabled and inference uses locally hosted models, indices and diagnostic tools. Available local case-literature corpora, including PMC-Patients, support retrieval without live PubMed requests. A service is used in this setting only if a local implementation and its required data are available. The diagnostic workflow is unchanged, while the available evidence sources depend on the setting.

`Config.allow_external_requests` defaults to `True`, permitting configured external services while preserving existing tool adapters. Setting it to `False` keeps only tools explicitly declaring `requires_external_access=False`; external and undeclared tools are omitted before inference. The reasoning and auxiliary models must also declare local access, otherwise diagnosis stops before any model or tool call.

`ConfiguredTool` attaches a source name, an access declaration and an `enabled` switch to an existing tool adapter. `enabled=False` excludes that source in either setting. It does not download data or replace the backend implementation. The following configuration accepts deployment adapters implementing the existing tool protocols; it assumes local PhenoBrain, local case and knowledge indices, and public PubCaseFinder. Set each access declaration according to the actual backend, including any requests made by a local MCP proxy.

```python
from genesis import Config, Models, Tools
from genesis.llm.openai_compat import OpenAIChat
from genesis.tools import ConfiguredTool, ModelPhenotypeExtractor, ModelEvidenceSummarizer

reasoner = OpenAIChat("http://localhost:8000/v1", "GENESIS-R1",
                      requires_external_access=False)
auxiliary = OpenAIChat("http://localhost:8001/v1", "Qwen3-8B", thinking=False,
                       requires_external_access=False)
models = Models(reasoner=reasoner, auxiliary=auxiliary)

def configure_sources(phenobrain, pubcasefinder, local_knowledge,
                      pubmed, wikipedia, web_search, local_cases):
    return Tools(
        phenotype_extractor=ModelPhenotypeExtractor(auxiliary),
        summarizer=ModelEvidenceSummarizer(auxiliary),
        expert_methods=[
            ConfiguredTool(phenobrain, "PhenoBrain", requires_external_access=False),
            ConfiguredTool(pubcasefinder, "PubCaseFinder", requires_external_access=True),
        ],
        knowledge_sources=[
            ConfiguredTool(local_knowledge, "Local knowledge", requires_external_access=False),
            ConfiguredTool(pubmed, "PubMed", requires_external_access=True),
            ConfiguredTool(wikipedia, "Wikipedia", requires_external_access=True),
            ConfiguredTool(web_search, "General web search", requires_external_access=True,
                           enabled=False),
        ],
        case_indices=[
            ConfiguredTool(local_cases, "Local cases", requires_external_access=False),
        ],
    )

config = Config(k=5, max_rounds=3, allow_external_requests=False)
```

The access switch selects adapters using their declarations; it is not an operating-system firewall. Deployments requiring enforced network isolation also restrict outbound traffic in their runtime environment. Model endpoints are classified separately from retrieval sources; an API on the local deployment network need not use the public internet. Auxiliary adapters inherit the access declaration of their model.

The bundled file-based example can run with `python3 examples/run_dataset.py --network disabled`. With locally hosted model endpoints, also supply `--model-access local` and, when used, `--auxiliary-access local`. External tools must be explicitly configured; network-enabled mode does not activate absent services. Source coverage may differ between settings.
