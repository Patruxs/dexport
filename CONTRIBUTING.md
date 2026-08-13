# Contributing to dexport

Thanks for helping. This file is the practical checklist; the *why* of the
design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the user-facing
story is in the [README](README.md).

## Setup

- Python **3.11+** (CI runs 3.11-3.14; `pyproject.toml` pins `requires-python = ">=3.11"`).
- `make install` creates `./.venv` and does `pip install -e ".[dev]"` (pytest, pytest-cov, ruff, mypy).
- Every `make` target uses `./.venv` automatically when it exists; override with `make PY=python3 test`.
- No `playwright install` is needed: dexport attaches to Discord's own Electron process, and the
  tests never start a browser or open a CDP connection (`tests/test_session.py` monkeypatches
  `playwright.sync_api.sync_playwright`, so the package only has to be importable).
- Optional: `pip install pre-commit && pre-commit install` runs ruff on commit (`.pre-commit-config.yaml`).

## The check loop

| Command | What it runs |
| --- | --- |
| `make test` | `pytest -q` (offline, sub-second) |
| `make lint` | `ruff check .` + `ruff format --check .` |
| `make typecheck` | `mypy dexport` (`strict = true`, `warn_unreachable`, config in `pyproject.toml`) |
| `make check` | lint + typecheck + test - exactly what CI (`.github/workflows/ci.yml`) runs |
| `make fmt` | `ruff check --fix .` + `ruff format .` - auto-fixes what it can |

Run a single test with `.venv/bin/python -m pytest tests/test_api.py::test_401_triggers_single_reauth -q`
(or `-k <substring>`). Ruff is configured with line length 100 and the rule sets
`E W F I UP B SIM C4 RUF BLE S`; a blind `except Exception` needs a `# noqa: BLE001 - <reason>`.
`UP` rules target `py311`, so ruff (not your interpreter, which may be newer) is what keeps
3.12+-only syntax out.
