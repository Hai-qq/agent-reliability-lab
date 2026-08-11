# OpenCode Go Two-Model Probe for v0.29

The fixed two-turn synthetic structured-tool probe passed for both frozen model
bindings before the v0.29 canary or formal matrix started.

- Flash: `opencode-go/deepseek-v4-flash/listing-2026-08-09/non-thinking`
- Qwen: `opencode-go/qwen3.7-plus/listing-2026-08-09/default-inference`
- 4 logical calls, 4 transport attempts, 0 retries, 0 typed failures.
- 2,103 input, 335 output, 218 reasoning, and 2,438 total tokens.

`probe.json` stores only bindings, typed outcomes, usage, transport counts,
digests, and sanitized checks. It contains no prompt, tool payload, provider
response body, or credential. Its SHA-256 is
`32cd608ece843f225814cd79936da6758a46621d3fa0348dda32bac0d368eb8e`.
