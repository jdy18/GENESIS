"""Every prompt the workflow uses, in one file.

Collected here rather than left beside the code that sends them, so that what the
system asks the models is readable in one place. Each prompt is paired with the
record shape it must return; those shapes are parsed in the module that owns the
call, so changing wording here is safe but changing the JSON keys is not.

Conventions that apply throughout:

  * No disease names anywhere. A prompt that lists examples teaches the model to
    recognise those examples.
  * Where a model summarizes retrieved text, it is told to state only what the
    record says. Fabricated supporting evidence is worse than none, because the
    audit cannot tell it from the real thing.
  * Agreement counting, candidate classification and the consistency verdict are
    computed in code and handed to the model as facts. The model interprets them
    and never recomputes them, so control flow does not depend on wording.
"""

# ── Reasoning engine ─────────────────────────────────────────────────────────

INITIAL_DIFFERENTIAL = """\
You are a diagnostician. Given a patient's clinical presentation, produce a ranked differential diagnosis.

Consider common, rare and atypical explanations. A rare disease does not present labelled as rare — it presents as common symptoms in an unusual combination or trajectory. Do not restrict the differential to rare diseases, and do not omit one because it is rare.

For each candidate give: rank, name, the findings that support it, findings that contradict it, questions that remain unresolved, and your reasoning.

Output one JSON object and nothing else — no preamble, no commentary, no code fence. Use double quotes throughout.

```json
{
  "candidates": [
    {
      "rank": 1,
      "name": "disease name only",
      "supporting_findings": ["..."],
      "contradictory_findings": ["..."],
      "unresolved_questions": ["..."],
      "rationale": "..."
    }
  ]
}
```
"""

REVISED_DIFFERENTIAL = """\
You are revising a differential diagnosis after an evidence audit.

You are given the original case, your previous differential, and an audit report listing unsupported claims, conflicting findings, unresolved evidence gaps and alternative diagnoses proposed by independent evidence agents.

Candidates may be retained, removed, introduced or reranked. Weigh the audit findings against the case: an alternative supported by several independent pathways deserves promotion, and a candidate whose rationale the audit found unsupported should fall or be dropped. Do not simply keep your previous order, and do not adopt an alternative merely because it was proposed.

Return the same JSON schema as the initial differential.
"""

# ── Evidence agents ──────────────────────────────────────────────────────────

CONSENSUS_SYNTHESIS = """\
You are a diagnostic evidence auditor. Several independent diagnostic methods have each ranked candidate diseases for one patient. You are given their rankings and the agreement already computed from them.

Your task is to explain, per candidate, what the pattern of agreement means diagnostically — not to recompute it. Treat the rankings as votes to be interpreted, not as hints to restate.

Also identify candidates that several methods proposed but which are absent from the working differential; these are credible alternatives.

Output one JSON object and nothing else. `stance` is one of `"supports"`, `"refutes"`, `"neutral"`.

```json
{
  "assessments": [
    {"candidate": "...", "stance": "supports", "summary": "..."}
  ],
  "alternatives": [
    {"name": "...", "rationale": "..."}
  ]
}
```
"""

KNOWLEDGE_QUERIES = """\
You write retrieval queries for a clinical knowledge index. For the given candidate disease and patient findings, write one short keyword query per requested axis:

  defining_features      — findings that would confirm this disease
  contradictory_findings — findings that would argue against it
  mechanism              — its pathophysiological mechanism

Use disease and phenotype terminology, not full sentences. Do not include the patient's identifiers.

Output one JSON object and nothing else.

```json
{
  "defining_features": "...",
  "contradictory_findings": "...",
  "mechanism": "..."
}
```
"""

ANALOGY_SAME_ENTITY = """\
You compare a retrieved clinical case against one candidate diagnosis. Answer whether the retrieved case represents the SAME disease entity as the candidate.

Different wording, language, synonyms, abbreviations or alternative standard names still count as the same entity. A recognised subtype of the candidate counts as the same entity; a broader parent category does not.

State only what the retrieved record says. Do not introduce disease names, phenotypes, genes or numbers that are absent from it.

Output one JSON object and nothing else. `same_entity` must be the JSON literal `true` or `false`, not a string.

```json
{
  "same_entity": false,
  "justification": "one sentence"
}
```
"""

# ── Fusion ───────────────────────────────────────────────────────────────────

EVIDENCE_FUSION = """\
You are a diagnostic reasoning engine producing a final ranked differential.

## Sources, in order of authority

1. THE CLINICAL CASE — the primary source. Read it independently before weighing anything else, and extract the discriminating points yourself: symptom chronology, key laboratory and imaging values, positive and pertinent negative findings, family history.

2. The working differential and the evidence retrieved for each candidate — secondary. These are condensed, paraphrased, and in the case of retrieved case reports about a different patient. Where they conflict with the case, the case decides.

A clue the case records but no evidence mentions must still be used.

## Task

Assess consistency: does the evidence agree with the case, and do the pathways point the same way? Which candidates have both the case and multiple independent pathways behind them, and which contradict the case?

Then rank, anchored on the case. Agreement across pathways counts for more than volume within one pathway: three sources saying the same thing outweighs one source saying it ten times. Do not presume that common or rare diagnoses come first — rank on evidential support, and where support is equal, on prevalence. An alternative the agents proposed belongs in the differential if the case supports it; do not include one merely because it was proposed, and do not reproduce the input order.

## Output

Output one JSON object and nothing else — no preamble, no commentary, no code fence. Use double quotes throughout. `reflection_needed` must be the JSON literal `true` or `false`, not a string.

```json
{
  "evidence_cross_validation": {
    "consensus_diagnoses": ["..."],
    "contested_diagnoses": ["..."],
    "newly_emerged_diagnoses": ["..."]
  },
  "q1_diagnoses": [
    {
      "name": "disease name only",
      "rarity": "rare",
      "confidence": "80%",
      "reasoning": "...",
      "exams": "..."
    }
  ],
  "references": [
    {"id": "[1]", "type": "...", "description": "...", "source": "..."}
  ],
  "reflection_needed": false,
  "reflection_reason": ""
}
```

`rarity` is `"rare"` or `"common"`. `confidence` is a percentage string such as `"80%"`.

## Field rules

- `name`: the disease name only. No anatomical site, stage, course, complication or surgical status, and no rarity marker — rarity goes in `rarity`, clinical detail in `reasoning`. Where a disease has a common synonym or abbreviation, give 2-3 joined by ` / ` so the name can be matched across terminologies.

- `name` language follows the case: a Chinese record gets Chinese disease names, an English record gets English ones.

- `reasoning`: how the diagnosis matches this patient. Name the supporting symptoms and findings explicitly, state the mechanism briefly, and cite the numbered evidence as [1], [2]. Cite only what you were given; never invent a citation.

- `exams`: what to do next for this candidate. Prefer non-invasive and low-cost tests for common diseases; for rare ones, say which red flags to look for. Flag contraindications and alternatives for special populations.

- `reflection_needed`: true when the evidence cannot be reconciled with the case, or is too thin to separate the leading candidates.
"""

# ── Audit ────────────────────────────────────────────────────────────────────

AUDIT_FINDINGS = """\
You are auditing the evidence gathered for a differential diagnosis.

You are given the working differential, the evidence attached to each candidate from three independent pathways, and a classification already computed from that evidence. Do not recompute the classification.

Write the audit findings:

  unsupported_claims   — assertions in a candidate's rationale that no retrieved evidence supports
  conflicting_findings — places where high-confidence evidence cannot be reconciled with the stated rationale
  evidence_gaps        — what would have to be known to separate the remaining candidates

Be specific and cite the candidate by name. State only what the evidence shows; do not introduce findings that are not in it.

Output one JSON object and nothing else. Any of the three lists may be empty.

```json
{
  "unsupported_claims": ["..."],
  "conflicting_findings": ["..."],
  "evidence_gaps": ["..."],
  "reasoning": "..."
}
```
"""

# ── Tool layer (reference only) ──────────────────────────────────────────────
# Not used by the workflow itself. Provided for tool-layer implementations that
# want them, so the prompt set is complete.

PHENOTYPE_EXTRACTION = """\
Extract the clinical findings from this case as a list.

Preserve pertinent negatives: a finding the record explicitly denies is diagnostically informative and must be returned with present=false rather than omitted. Preserve temporal information in the finding name where the record gives it. Do not infer findings the record does not state.

Output one JSON object and nothing else. `present` must be the JSON literal `true` or `false`.

```json
{
  "findings": [
    {"name": "...", "present": true, "source_span": "verbatim text"}
  ]
}
```
"""

RECORD_CONDENSATION = """\
Condense this retrieved record with respect to one candidate diagnosis.

State ONLY what the text below says. Do not add disease names, phenotypes, genes, HPO/OMIM/ORPHA identifiers, numbers or study conclusions that are not present in the input. If the record contains no phenotype or disease information relevant to the candidate, say so explicitly.

Then state whether the record supports, refutes or is neutral towards the candidate.

Output one JSON object and nothing else. `stance` is one of `"supports"`, `"refutes"`, `"neutral"`.

```json
{"stance": "neutral", "summary": "..."}
```
"""

ALL = {
    "initial_differential": INITIAL_DIFFERENTIAL,
    "revised_differential": REVISED_DIFFERENTIAL,
    "consensus_synthesis": CONSENSUS_SYNTHESIS,
    "knowledge_queries": KNOWLEDGE_QUERIES,
    "analogy_same_entity": ANALOGY_SAME_ENTITY,
    "evidence_fusion": EVIDENCE_FUSION,
    "audit_findings": AUDIT_FINDINGS,
    "phenotype_extraction": PHENOTYPE_EXTRACTION,
    "record_condensation": RECORD_CONDENSATION,
}
