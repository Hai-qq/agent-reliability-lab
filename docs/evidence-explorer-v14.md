# ARL Evidence Explorer v0.14

Evidence Explorer v0.14 is the public-facing, read-only evidence layer for Agent Reliability Lab. It normalizes the four latest product increments into one compact offline page while retaining direct links to their frozen machine-readable summaries and contract documents.

The explorer does not copy session, episode, event or raw intent payloads. It embeds only aggregate metrics, counts, local links and recorded hashes.

## Verified inputs

| Increment | Product gate shown | Rechecked traces |
|---|---|---:|
| v0.10 Study Runtime | 13/13 pre-resume results preserved; 36/36 complete | 36 |
| v0.11 Parallel Study | 36/36 exactly-one final commits | 36 |
| v0.12 Scenario Pack | 12/12 compatible recovery; 12/12 changed-target classification | 72 |
| v0.13 Symbolic User | 192/240 non-direct SafeSuccess; 0 unsafe commits | 720 |

The headline percentages are increment-specific saved gates. They are deliberately labelled as such and must not be read as a cross-version benchmark ranking.

## Fail-closed build

Before rendering, the builder:

1. reloads all four formal summaries and their independent repeats;
2. recomputes every referenced source SHA-256 from the current checkout;
3. recomputes all 864 formal trace hashes and compares them to the repeat and recorded manifest;
4. requires every saved `all_selected_checks_passed` gate to remain true;
5. requires all saved runs to report synthetic-only data, zero model calls and zero external network calls;
6. audits the final HTML for external scripts, network APIs and mutating form controls.

Any failed input prevents output generation. Existing output directories are never overwritten.

The public repository stores the full v0.10–v0.13 trace/workspace subtrees in [v0.15 deterministic bundles](./release-bundle-v15.md) to avoid thousands of repeated Git entries. The committed Explorer opens directly; rebuilding it from a fresh clone requires restoring those bundles first.

## Viewer behavior

`index.html` contains all CSS, JavaScript and aggregate JSON inline. It provides:

- responsive product cards for Study, Parallel, Scenario and Authorization layers;
- category filters and expandable source/trace integrity details;
- direct relative links to formal `summary.json` and the matching contract/limits document;
- one integrity table covering saved validity, source manifests, summary parity, trace parity and the local synthetic boundary.

The page makes no network request and has no runtime control, upload, form, `contenteditable` region or external asset. Browser QA covered the default desktop viewport and a 390×844 mobile viewport, filter/detail interaction, local artifact navigation and console errors.

## Fixed evidence

Formal and repeat outputs are byte-identical. Fixed hashes:

```text
evidence.json: 21375d1c64701f71dedcbd82182d7b3e84fabcf5dd3634b0c1721a926012881a
index.html:    bb1935446343c1901f38e8a5c0cc297cae436390979086513d676dff9ef7d2dd
source:        ca594a156126f9feb30be1fef4760b08b087abe7faa63c3e5de73c35376df2be
```

## Evidence

- [Open the hosted Evidence Explorer](https://hai-qq.github.io/agent-reliability-lab/)
- [Open offline Evidence Explorer](../artifacts/evidence_explorer_v14/index.html)
- [Machine-readable evidence catalog](../artifacts/evidence_explorer_v14/evidence.json)
- [Independent repeat](../artifacts/evidence_explorer_v14_repeat/)
- [Commands, versions, browser QA and hashes](../artifacts/evidence_explorer_v14/validation.log)

## GitHub Pages deployment

`.github/workflows/pages.yml` publishes only tracked files under `artifacts/` and `docs/`, plus a root redirect to the Explorer. Local ignored trace/workspace trees, source code, tests and research notes are not copied into the Pages artifact. The workflow runs on `main`, on the authorized `agent/reliability-suite-v015` release branch for pre-merge verification, and by manual dispatch.

All four GitHub Actions are pinned to full commit SHAs. The build job receives only `contents: read` and `pages: read`; the deploy job receives only `pages: write` and OIDC `id-token: write`. Concurrent deployments are serialized.

The authorized pre-merge deployment [run 31233748160](https://github.com/Hai-qq/agent-reliability-lab/actions/runs/31233748160) succeeded on 2026-08-08 for commit `0f4e510a6ec1ed4fe07bea4ef8e1923f53b38eb5`. The canonical root, Explorer, evidence catalog, Study summary and contract document each returned HTTP 200. The hosted Explorer and evidence catalog matched the frozen SHA-256 values above byte for byte. The `github-pages` environment allows only `main` and the exact `agent/reliability-suite-v015` release branch.

## Boundaries

- the linked frozen artifact, not this aggregate page, is the evidence of record;
- fixed local synthetic tasks and deterministic policies only;
- no natural-language/model capability or real-user claim;
- no API, external network, account, credential, personal data or real system;
- no prompt-injection suite, attack/defense operation or transferable adversarial material.
