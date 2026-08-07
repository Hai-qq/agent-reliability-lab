# Agent Reliability Lab project rules

- Keep experiments local, synthetic, and isolated. Do not use real accounts, real network targets, credentials, or third-party systems.
- Do not add or run model/API integrations, prompt-injection suites, or attack/defense material without explicit user authorization.
- Treat saved scripts, JSON, JSONL traces, test logs, and source manifests as the evidence of record; documentation alone is not completion proof.
- Preserve existing reproduction artifacts. New runners must refuse to overwrite prior result or trace paths.
- Use Python 3.11 or newer. Prefer the standard library and update `pyproject.toml` plus lock/config files if dependencies are added.
- Run the core suite with `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py'`.
- Run `ruff check src scripts tests` and `ruff format --check src scripts tests` after source changes.
- Keep raw task payloads, synthetic records, and model content out of committed traces; store digests and typed metadata unless a reviewed exemplar requires more.
- Update `README.md`, relevant `docs/`, artifact validation logs, and `THIRD_PARTY.md` when behavior, scope, dependencies, or evidence changes.
