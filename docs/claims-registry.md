# Claim registry

This registry is a fail-closed map from exact public wording to the evidence and
validity gates that permit it. The installed machine-readable source is
`arl.registry.CLAIMS`; the Evidence Explorer and `arl claims` consume that same
source. A positive descriptive aggregate is never sufficient to upgrade a claim.

## Status vocabulary

- `BLOCKED`: a required readiness or inference gate failed.
- `INVALID_FOR_INFERENCE`: the saved study is retained, but neither confirmatory nor
  exploratory inference is authorized.
- `NO_RESULTS`: a protocol or scripted preflight exists without model outcomes.
- `NOT_MATERIALIZED`: the public checkout lacks the episode-level evidence needed for
  independent recomputation.

## ARL-V028-INFRASTRUCTURE

| Field | Value |
| --- | --- |
| `claim_id` | `ARL-V028-INFRASTRUCTURE` |
| Exact claim text | The saved v0.28 infrastructure checks passed, but Qwen readiness failed. |
| `study_id` | `opencode-go-flash-qwen-v0.28` |
| `source_commit` | `71792c832b17cbf362f3a4a14e7e81b2b14426e9` |
| Study contract | `v0.28` |
| Task catalog | `main-pack-v1` |
| Model/provider binding | OpenCode Go gateway; Flash and Qwen slots |
| Preregistration | Registered contract; confirmatory gate not reached |
| Infrastructure valid | `true` |
| Readiness valid | `false` |
| Analysis mode | `exploratory_only` |
| Claim status | `BLOCKED` |
| Public evidence | `SUMMARY_AND_EXPLORATORY_ANALYSIS_ONLY` |
| Independent replication | `NOT_REPORTED` |
| Supersedes / superseded by | none / none |

Limitations: Qwen readiness failed, so no confirmatory claim is permitted. Both model
slots used the same gateway; this is not cross-provider replication. The compact
public checkout does not provide an `arl-evidence-v1` episode ledger for this study.

## ARL-V029-DESCRIPTIVE

| Field | Value |
| --- | --- |
| `claim_id` | `ARL-V029-DESCRIPTIVE` |
| Exact claim text | The v0.29 run completed 2,592 scheduled episodes, but its saved outcomes are descriptive only. |
| `study_id` | `opencode-go-holdout-v0.29` |
| `source_commit` | `71792c832b17cbf362f3a4a14e7e81b2b14426e9` |
| Study contract | `v0.29` |
| Task catalog | `holdout-pack-v1` |
| Model/provider binding | OpenCode Go gateway; Flash and Qwen slots |
| Preregistration | Registered holdout; inference gates failed |
| Infrastructure valid | `false` |
| Readiness valid | `false` |
| Analysis mode | `descriptive_aggregates_only` |
| Claim status | `INVALID_FOR_INFERENCE` |
| Public evidence | `NOT_MATERIALIZED` |
| Independent replication | `NOT_REPORTED` |
| Supersedes / superseded by | none / none |

The immutable summary records all 2,592 scheduled episodes, two unrecovered Qwen HTTP
503 outcomes, and four Qwen violations of the frozen USD 0.01 episode cap. Therefore
infrastructure validity failed, Qwen readiness failed, confirmatory analysis is
blocked, and exploratory inference is also blocked. Only saved descriptive aggregates
may be reported. The ignored full summary/study ledger is absent from a fresh public
checkout, so the public episode evidence remains `NOT_MATERIALIZED`.

## ARL-V030-DESIGN

| Field | Value |
| --- | --- |
| `claim_id` | `ARL-V030-DESIGN` |
| Exact claim text | v0.30 is a design and scripted-preflight contract; it contains no model-performance result. |
| `study_id` | `arl-study-v0.30.0` |
| `source_commit` | `PENDING_FUTURE_EXECUTION_COMMIT` |
| Study contract | `arl-study-v0.30.0` |
| Task catalog | `arl-planning-tasks-v0.30.0` |
| Model/provider binding | `UNBOUND_MODEL_SLOTS` |
| Preregistration | Design only, pending external execution |
| Infrastructure valid | unknown |
| Readiness valid | unknown |
| Analysis mode | `preregistered_design_only` |
| Claim status | `NO_RESULTS` |
| Public evidence | `SCRIPTED_FIXTURE_ONLY` |
| Independent replication | `PENDING_EXTERNAL_REPLICATION` |
| Supersedes / superseded by | none / none |

The scripted oracle, schedule, budget, evaluator-mutation, and evidence-verifier checks
exercise infrastructure only. They are not agent outcomes and must never be plotted or
described as model performance.

## Claim promotion rule

A claim may be labelled confirmatory only when its exact wording was preregistered and
all required public evidence is materialized; source, schedule, catalog, file and trace
links verify; infrastructure and readiness gates pass; the registered estimand and
decision rule pass; and the provider/model binding matches the manifest. Missing facts
remain `unknown`, `pending external replication`, or `not materialized`.
