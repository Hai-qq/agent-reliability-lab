# ARL Symbolic User v0.13

Symbolic User v0.13 adds a stateful authorization protocol to the four existing Retail and Travel reliability templates. It tests whether a runtime can obtain complete intent, detect a pre-commit revision, and bind the final write to a current authorization token. The users are deterministic finite-state actors with structured responses, not language models.

## Authorization contract

Each task template has one audited intent schema. The schema lists required fields and exactly one field that can change before commit. Raw intent values never enter the JSONL journal; runtime events contain only revision numbers, counts, typed statuses, state hashes and digests.

An authorization token binds four facts:

```text
session ID + intent revision + intent digest + token digest
```

A commit is safe only when the token is authentic and current, every required field is present, and the proposed intent digest equals the latest user intent. Missing, tampered or stale authorization fails closed.

## Policies and user conditions

| Policy | Behavior |
|---|---|
| `one_shot` | Requests once, never clarifies or checks freshness, then attempts commit. |
| `revision_aware` | Requests exact missing fields, checks token freshness, reauthorizes once after a revision, and safely aborts if the user disengages. |

Both policies run on the same deterministic paired cohort under three conditions:

- direct approval with complete, stable intent;
- one missing required field that needs exact clarification;
- one authorized intent revision immediately before commit.

Clarification and revision cohorts use a fixed digest-derived engagement decision. This creates repeat-to-repeat variation while preserving exact reproducibility and paired comparison.

## Fixed matrix and results

```text
4 templates × 2 policies × 3 conditions × 5 seeds × 6 repeats = 720 sessions
```

| Condition | One-shot | Revision-aware |
|---|---:|---:|
| Direct approval | 120/120 SafeSuccess | 120/120 SafeSuccess |
| Clarification required | 120/120 unsafe commit | 107/120 SafeSuccess; 13 safe abort |
| Pre-commit revision | 120/120 unsafe commit | 85/120 SafeSuccess; 35 safe abort |

Revision-aware produced 0 unsafe commits across all 360 sessions. Its clarification SafeSuccess rate was `0.8917` (Wilson 95% interval `[0.8234, 0.9356]`; six-repeat sample standard deviation `0.0861`). Its revision SafeSuccess rate was `0.7083` (Wilson 95% interval `[0.6216, 0.7822]`; sample standard deviation `0.1158`). These intervals summarize the fixed synthetic cohort and do not estimate real-user behavior.

The downstream gate additionally requires all four directly approved sessions to pass their existing Scenario Pack state evaluator. Authorization success alone is therefore insufficient evidence of task success.

## Validity gates

- 360 paired cohorts contain exactly one run per policy and share the same engagement outcome;
- incomplete intent makes one-shot produce `authorization_missing`;
- revision makes the old token `stale`, and token tampering is `invalid`;
- revision-aware performs two freshness checks around reauthorization and never commits after abandonment;
- all four schemas are digest-linked to the existing task templates;
- 720 traces contain no raw intent field values, synthetic records, task payload or engagement flag;
- v0.1–v0.12 recorded source manifests remain unchanged;
- a shadow 720-session run is identical after excluding only trace filenames.

Formal and repeat summaries plus 720/720 traces are byte-identical. Fixed hashes:

```text
summary: b74aa2ae26d6b5565000c06055da6fe8d69f2f060c0fdf3bd87edd08bf7d2d2c
source:  fd3f5f31031c4adc2bffc43ee365f26f89e88b41044be7eec6dd624e50e076f3
traces:  f69fea8f829ff047f734b30483c73ae75b4bed59fd361c5dcc720c6b67f1ae7b
```

## Evidence

- [Formal summary](../artifacts/symbolic_user_v13/summary.json)
- [720 formal trace bundle](../artifacts/release_bundle_v15/bundles/symbolic-user-v13-traces.zip)
- [Independent repeat](../artifacts/symbolic_user_v13_repeat/)
- [Commands, versions, hashes and gates](../artifacts/symbolic_user_v13/validation.log)
- [Per-file bundle manifest and restore targets](../artifacts/release_bundle_v15/manifest.json)

## Boundaries

- finite-state structured users, not natural-language or model-driven dialogue;
- four fixed templates, five fixed seeds and six fixed repeats;
- digest-derived abandonment is a benchmark condition, not a human-population model;
- no model/API call, network access, account, credential, personal data or real system;
- no prompt injection, attack/defense suite or transferable adversarial material.
