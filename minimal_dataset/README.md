# minimal_dataset

Three cases and three small indices, enough to run the workflow end to end
without connecting a retrieval stack. `examples/run_dataset.py` wires them up.

Nothing here is patient data: the cases are written for this repository, and the
index entries are short reference summaries rather than copied source text.

## Cases

`cases/*.json`

| Field            | Meaning                                                                        |
| ---------------- | ------------------------------------------------------------------------------ |
| `case_id`        | identifier                                                                     |
| `input_type`     | `free_text` or `phenotype_list`                                                |
| `language`       | `en` or `zh`                                                                   |
| `clinical_text`  | the record the workflow reads                                                  |
| `phenotypes`     | optional pre-extracted findings, with `present: false` for pertinent negatives |
| `gold_diagnosis` | reference answer                                                               |
| `gold_synonyms`  | acceptable alternative names                                                   |
| `notes`          | what the case is meant to exercise                                             |

The three cover the input shapes the workflow has to handle:

- **case_001** — English narrative with laboratory values, imaging and
  histology. The discriminating feature (stroke-like episodes across vascular
  territories) separates the answer from a near neighbour that shares the biopsy
  finding.
- **case_002** — pre-extracted phenotype list with two pertinent negatives. The
  absent finding is what distinguishes the attenuated form from the severe one,
  so an implementation that drops negatives loses the discriminator.
- **case_003** — Chinese narrative whose decisive clues (urine darkening on
  standing, hyponatraemia during attacks, one affected relative) live in the
  prose and would not survive extraction into ontology terms alone.

## Indices

`indices/knowledge.json` — records for `KnowledgeSource`. Each has `id`,
`title`, `text`, `source`, `score`. Includes near neighbours as well as correct
answers, so ranking has something to do.

`indices/cases.json` — records for `CaseIndex`, with `case_id`, `diagnosis`,
`summary`, `shared_terms`, `cross_encoder_score`. Includes one entry per case
that is a different disease sharing findings, which the same-entity check should
reject.

`indices/expert_rankings.json` — ranked lists per case, keyed by method name,
for `ExpertMethod`. The two methods disagree on order, which is what gives the
consensus pathway something to weigh.
