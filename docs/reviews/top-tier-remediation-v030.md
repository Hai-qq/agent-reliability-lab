# Top-tier remediation baseline and execution record

## Frozen baseline

- Repository: `https://github.com/Hai-qq/agent-reliability-lab`
- Branch: `main`
- Baseline commit: `71792c832b17cbf362f3a4a14e7e81b2b14426e9`
- Baseline distribution version: `0.3.0`
- Remediation distribution version: `0.4.0`
- Baseline artifact inventory: 464 tracked Git blobs, 13,968,008 bytes
- Canonical baseline artifact digest:
  `5d80a1b067fc17bc7c8a21772386037d049eb4d8253aafbb1bcee1e9176a2922`

The artifact digest is SHA-256 over canonical JSON mapping every tracked Git blob path
below `artifacts/` to the SHA-256 of its blob bytes. Using Git blobs makes this baseline
independent of checkout-specific LF/CRLF conversion. Historical artifacts are immutable
inputs to this remediation. Their study identifiers and package versions remain
historical; the distribution version does not rewrite them.

## Baseline verification result

The release bundle restore completed without a provider or network call:

```text
Restored 8 artifact targets with 1880 file writes
```

The required baseline command was then run on Python 3.11.9 / Windows / SQLite 3.45.1:

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -p 'test_*.py'
```

It ran 239 tests in 18.615 seconds and failed with 12 errors before any tracked file
was changed. The errors form three implementation defects:

1. Evidence, scenario, and symbolic validity reporters iterate over their newly added
   boolean aggregate as though it were a check object (`bool.get` failure).
2. Trace writers use translated text mode on Windows. The in-memory LF bytes used for
   a declared digest differ from the CRLF bytes written to disk, so study and parallel
   schedulers reject valid local traces.
3. Several validity gates compare historical source manifests to the current worktree.
   That is not a valid historical-integrity test: v0.3 and v0.8 already record a
   different `pyproject.toml` from the baseline checkout.

These failures are baseline facts, not regressions introduced by the remediation. They
will be covered by targeted regression tests and the full suite will be rerun after the
implementation.

## Non-negotiable execution boundaries

- No provider, model, or external experiment call is permitted during remediation.
- No API key is read, created, requested, logged, or stored.
- v0.28 and v0.29 are not rerun and their thresholds are not lowered.
- Existing experiment results, traces, summaries, manifests, and validation logs are
  not edited in place.
- v0.28 remains exploratory because the Qwen readiness gate failed.
- v0.29 remains descriptive only: infrastructure validity and Qwen readiness failed;
  the saved study includes two unrecovered Qwen HTTP 503 outcomes and four Qwen budget
  violations.
- The public repository does not contain the v0.29 full episode ledger and traces.
  Verification must report that evidence as `not_materialized`, never reconstruct or
  imply it.
- Confirmatory wording may only be emitted for a preregistered claim whose required
  public evidence, integrity checks, readiness gates, and statistical decision all
  pass. Otherwise the claim is explicitly descriptive, exploratory, blocked, or not
  materialized.

## Migration strategy

The remediation adds a stable `arl` facade, a versioned public evidence contract, and a
single fail-closed CLI while keeping historical implementation packages available for
reproduction. Historical source verification is separated from current-worktree
verification: current files are checked directly when unchanged, and prior bytes are
resolved from Git history when a historical manifest intentionally names an older
snapshot. Public bundles are deterministic canonical JSON/JSONL plus gzip with
`mtime=0`; private-to-public export is deny-by-default and rejects unknown fields.

The release is evaluated in layers:

1. schema and semantic validation of public evidence;
2. byte-level manifest and cross-file reference validation;
3. claim-state derivation from declared evidence requirements;
4. deterministic descriptive and paired analyses;
5. package, CLI, clean-environment, and cross-platform checks;
6. release provenance, SBOM, checksum, and source-manifest checks.

## Completion record

This section is intentionally updated only with verified outcomes. Planned work is not
reported as complete.

| Gate | State | Evidence |
| --- | --- | --- |
| Frozen baseline | verified | Commit and artifact digest above |
| Historical artifact immutability | verified | 464 Git blobs, 13,968,008 bytes, canonical digest unchanged; dedicated byte test passes |
| Public evidence schema and verifier | verified | Five generated schemas, 54 valid smoke episodes, mutation/fail-closed tests, deterministic rebuild |
| CLI and offline smoke bundle | verified locally | Clean-wheel install, `arl --help`, smoke generation, and verifier pass |
| Statistical and budget audit | verified locally | Paired estimands, cluster bootstrap, exact tests, reservation/reconciliation, and v0.29 diagnostics pass |
| v0.30 design-only protocol | verified locally | 48 templates, 10,368 scheduled cells, all scripted checks pass, zero provider/model/network calls |
| Packaging and release automation | verified locally | Wheel/sdist, SBOM, source manifest, evidence ZIP, and checksums pass; remote release not executed |
| Documentation and Evidence Explorer v2 | verified locally | Generated output is current; browser layout/filter/link checks pass with no console log entries |
| Full repository verification | verified locally | 294 tests pass; scoped branch coverage 79%; lint, format, typing, schema, docs, and workflow checks pass |

## Final local verification ledger

The final acceptance run used Windows 10 build 26200, Python 3.11.9, SQLite
3.45.1, and Ruff 0.16.4. The complete `unittest` discovery ran 294 tests in
25.041 seconds with no failure. Coverage over the new evidence, analysis, study, and
CLI surfaces was 79%, above the configured 70% threshold. A fresh sdist and wheel were
built from the current tree; the wheel passed a clean-environment CLI/smoke/verifier
check, and all generated release checksums matched.

The Evidence Explorer was served locally after its final generation. Browser inspection
confirmed all four study cards, the v0.29 HTTP 503/budget/evidence limitations, the
54-episode smoke card, the R2 filter, and working bundle/manifest responses. The page
reported no console log entries. These are local acceptance results: the GitHub-hosted
OS/Python matrix, Pages deployment, CodeQL, dependency review, Scorecard, release
environment protection, and tag release remain external GitHub operations and were not
represented as run in this checkout.
