# Evidence Explorer v2

Evidence Explorer v2 is generated from `arl.registry` claim/study records, the
`arl-evidence-v1` schema, and verified public bundles under `evidence/`. It does not
parse prose or recompute statistics in JavaScript. Paired counts, intervals, errors,
cost, and latency are displayed only when Python has materialized them in a verified
public bundle; otherwise the UI says they are not materialized.

Regenerate and check determinism with:

```bash
python scripts/build_evidence_explorer_v2.py
python scripts/build_evidence_explorer_v2.py --check
arl verify evidence/arl-smoke-v1
```

The page lists every registered study, including invalid, blocked, descriptive, and
design-only states. Model/runtime/domain/fault filters operate only on public episode
facets. v0.28/v0.29 remain visible even though no public v1 episode ledger exists.
Each materialized study links both its public manifest and a deterministic downloadable
ZIP generated from the same verified bundle bytes. ZIP members use normalized names,
timestamps, modes, ordering, and `ZIP_STORED`; avoiding deflate makes the archive bytes
independent of the runner's zlib implementation.
