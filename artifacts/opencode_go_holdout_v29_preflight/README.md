# Prospective Holdout v0.29 Preflight

This public-safe artifact records the final zero-model gate for the v0.29
three-seed holdout.

- 432/432 scripted episodes completed.
- All 16 selected validity checks passed.
- Clean `SafeSuccess` was 216/216; R2 fault `SafeSuccess` was 72/72.
- The run made zero model and zero external network calls.
- The frozen 51-file source manifest is
  `d2b413603354baf07e1c08932b0cb12070fafe77f609f232016636e095ffbf20`.

An earlier local-only chain was rejected after an over-broad trace audit
misclassified public task/tool identifiers. Its provider evidence was not
reused. The audit was corrected before this source freeze, and the complete
preflight, probe, canary, and formal chain was rerun from new output paths.

`summary.json` is the compact public record. The 1.45 MB full summary and 432
digest-only traces remain local and are excluded by `.gitignore`; their hashes
are retained in the compact record and `validation.log`.
