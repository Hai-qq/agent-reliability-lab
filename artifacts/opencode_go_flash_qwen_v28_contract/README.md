# OpenCode Go Flash + Qwen v0.28 Contract Gate

This artifact freezes the prospective ARL v0.28 design before any Qwen main-pack
benchmark outcome is observed. It is implementation evidence, not a model result.

The contract binds OpenCode Go `deepseek-v4-flash` and `qwen3.7-plus`, requires
a digest-only two-turn Qwen protocol probe, then a valid 12-episode canary, then
a fresh 864-episode formal matrix. The formal runner rejects stale or missing
prerequisite artifacts by comparing source hashes before creating its workspace.

See [the experiment contract](../../docs/opencode-go-main-v28.md) and
[`validation.log`](./validation.log). The live probe, canary, and formal run were
subsequently completed in separate, non-overwriting paths. Their current
disposition is recorded in the [main result artifact](../opencode_go_flash_qwen_v28/README.md).
