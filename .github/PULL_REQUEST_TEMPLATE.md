## What and why

<!-- One or two sentences. Link the issue if there is one: Fixes #123 -->

## Checklist

- [ ] `make check` passes (ruff check + ruff format --check + mypy --strict + pytest)
- [ ] New behaviour has a test, and the tests stay **offline and sleep-free**
      (inject `clock` / `sleeper` / `jitter` rather than sleeping)
- [ ] Docs updated where they track the code: `README.md` tables,
      `CHANGELOG.md` under `[Unreleased]`, `docs/ARCHITECTURE.md` if a stage changed
- [ ] No header, token, or account identifier is logged, printed, or persisted
- [ ] New sub-package under `dexport/`? Added to `packages` in `pyproject.toml`
- [ ] New write verb? Built in `messages.py` and routed through `run_write`

## Anything reviewers should look at closely

<!-- Trade-offs, things you were unsure about, deliberate non-fixes. -->
