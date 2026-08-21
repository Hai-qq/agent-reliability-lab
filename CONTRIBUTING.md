# Contributing

Thank you for improving Agent Reliability Lab. Contributions should make the local
runtime, stateful benchmark, methodology, or evidence chain more reproducible without
rewriting historical results.

## Development environment

Python 3.11–3.14 is supported. Core runtime dependencies are empty; tooling is optional.

```bash
git clone https://github.com/Hai-qq/agent-reliability-lab.git
cd agent-reliability-lab
python -m pip install -e ".[dev,validation]"

python scripts/manage_artifact_bundles.py restore \
  --bundle-dir artifacts/release_bundle_v15 --project-root .
python -m unittest discover -s tests -p "test_*.py"
ruff check src scripts tests examples
ruff format --check src scripts tests examples
mypy src/arl/evidence src/arl/analysis src/arl/studies src/arl/cli.py
arl verify evidence/arl-smoke-v1
python scripts/sync_evidence_schemas.py --check
python scripts/build_evidence_explorer_v2.py --check
```

The restore command is for a fresh clone and refuses to overwrite existing artifact
targets. Do not delete a local evidence tree merely to make restore pass.

## Adding an environment

Implement `arl.environments.StatefulEnvironment` with deterministic `reset`, typed
`step`, and integrity-hashable `snapshot`. Use project-owned synthetic records, logical
time, explicit schema versions, and state-level invariants. Add clean/fault tests,
deterministic reset tests, and a minimal example or study binding.

## Adding a fault

Implement `arl.faults.FaultInjector` and publish a fault contract containing the
precondition, exact injection point, observable symptom, hidden ground truth,
valid/prohibited recovery sets, required final invariants, forbidden side effects,
recoverability, applicable runtime mechanism, and mutation tests. A new task ID alone
is not an unseen fault mechanism.

## Adding an evaluator

Implement `arl.evaluation.StateEvaluator`. Bind each clause to an allowlisted public
state path and normalized event evidence. Tests must reject do-nothing, false-success,
duplicate-side-effect, unsafe-retry, and relevant state mutations. A trace hash alone
does not establish an evaluator outcome when the trace is unavailable.

## Adding a study

Freeze a separately versioned study contract, task/fault/evaluator catalogs, source
commit, model/provider binding, token budget, optional model-specific monetary policy,
readiness and infrastructure gates, schedule seed/order, estimands, missing/error rules,
and claim wording before execution. R1/R2 are the primary v0.30 comparison; R0 is
descriptive. Resume must retain the frozen order.

Run the complete scripted preflight first. Scripted oracle results validate the harness
and must never be presented as model performance. Provider execution requires separate
authorization and is never a routine PR/CI step.

## Generating evidence

Use the strict normalized interchange and explicit state allowlist:

```bash
arl bundle PRIVATE_DIR --public-output evidence/STUDY_ID \
  --public-state-field status --public-state-field another_synthetic_field
arl verify evidence/STUDY_ID
```

Unknown fields, secret-like content, non-canonical ledgers, missing/duplicate/extra
cells, digest mismatches, and evaluator inconsistencies fail closed. Never persist API
keys, authorization headers, cookies, raw prompts, raw responses, raw reasoning, hidden
system prompts, real account information, or unallowlisted state.

## Artifact immutability

Existing tracked artifacts are evidence of record. Do not overwrite, delete, reformat,
or regenerate them in place. New runners must require a non-existing output path. A
corrected publication receives a new bundle/version and an explicit supersession link;
historical study validity and thresholds do not change.

## Provider authorization boundary

Do not add or run a model/API integration without explicit authorization for that
study, provider, model, cost, and data scope. Authorized adapters may read a credential
only from the documented environment variable, process project-owned synthetic
payloads, reserve the maximum legal response before the call, and record only normalized
digest/usage/error metadata. Never put credentials in arguments, config, logs, traces,
issues, or fixtures. CI must not call providers.

## Reporting a failed reproduction

Use the reproducibility-report issue template. Include the source commit, distribution
and study versions, platform/Python/SQLite versions, exact offline command, verifier
output, artifact/bundle digests, and the first divergent check. Do not attach secrets or
raw third-party content. Preserve negative outcomes and mark unavailable evidence as
`NOT_MATERIALIZED` rather than reconstructing it.

## Pull requests

Describe changed contracts and user-visible behavior, tests actually run, artifact
integrity result, documentation updates, and known limits. Keep changes scoped; avoid
whole-repository formatting or historical package migration. See [SECURITY.md](./SECURITY.md),
[methodology](./docs/methodology.md), and [third-party provenance](./THIRD_PARTY.md).
