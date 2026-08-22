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
| `make typecheck` | `mypy src` (`strict = true`, `warn_unreachable`, config in `pyproject.toml`) |
| `make check` | lint + typecheck + test - exactly what CI (`.github/workflows/ci.yml`) runs |
| `make fmt` | `ruff check --fix .` + `ruff format .` - auto-fixes what it can |

Run a single test with `.venv/bin/python -m pytest tests/test_api.py::test_401_triggers_single_reauth -q`
(or `-k <substring>`). Ruff is configured with line length 100 and the rule sets
`E W F I UP B SIM C4 RUF BLE S`; a blind `except Exception` needs a `# noqa: BLE001 - <reason>`.
`UP` rules target `py311`, so ruff (not your interpreter, which may be newer) is what keeps
3.12+-only syntax out.

## How the tests are organised

Everything under `tests/` runs without Discord, without a real Playwright/CDP connection and
without the network.
The shared fakes live in `tests/conftest.py` (import them with `from conftest import FakeApi`):

- `dexport_home` (autouse) points `DEXPORT_HOME` at a temp dir and clears `DEXPORT_PORT` /
  `DEXPORT_DISCORD_BINARY`, so no test can read or write your real `~/.dexport`.
- `FakeSession([...])` + `resp(status, body, headers, error)` / `json_resp(status, payload)` stand in
  for the CDP session when testing `ApiCore` (`tests/test_api.py`). It records every payload in `.calls`.
- `FakeApi` stands in for `ApiCore` where code takes one (`messages.py`, `resolver.py`, CLI helpers):
  `api.queue(status, payload)` queues an `ApiResponse`, `api.calls` is a list of `(METHOD, path, body)`,
  and an unexpected extra request raises.
- `resolver_cache` is a ready-made `cache.json` dict with Vietnamese names for diacritics tests.
- `no_sleep_limiter` is a `RateLimiter` with `clock`/`sleeper`/`jitter` stubbed out.

**No test may sleep.** Anything time-dependent takes injectable callables: `RateLimiter(clock=, sleeper=,
jitter=)`, `human_pause(sleeper=, jitter=)`, `ensure_discord(wait_timeout=, poll_interval=)`. Pure
functions are split out precisely so they can be tested directly: `session.py`'s `is_discord_url` /
`score_page` / `pick_app_page`, `launcher/discovery.py`'s `candidate_paths(system=, home=, env=,
probe_flatpak=False)` and `launch_command`, `headers.py`'s `sanitize_headers`, `render.py`'s exporters.
Do not edit `conftest.py` for one test's convenience; put helpers in your own test module.

## Invariants that must not break

- **On-disk formats are stable.** `config.json` is exactly the `Settings` dataclass fields
  (`port`, `discord_binary`, `floor_delay_min`, `floor_delay_max`) and
  `tests/test_config.py::test_settings_roundtrip_preserves_json_keys` asserts the full dict.
  `cache.json` is `{"guilds": list | None, "channels": {guild_id: [ChannelRef]}}` and
  `resolver.normalize_cache` must keep repairing anything older or corrupt. Missing/corrupt files
  always fall back to defaults, never raise.
- **Nothing sensitive on disk.** The captured headers (including `authorization`) live only in
  `ApiCore.headers` for the lifetime of one command. Never log, print, cache or persist them, and
  never add a header-shaped key to either JSON file.
- **CLI surface and output are user-facing.** Global flags (`--port/--restart/--binary/--version`)
  go before the sub-command; every channel command accepts the `-g/-c/--guild-id/--channel-id`
  quartet from `cli/common.py`; expected failures print `error: ...` to stderr and exit 1 via
  `fail()`. The README command and config tables are guarded by `tests/test_docs.py`.
- **Write verbs always confirm unless `--yes`.** `run_write` calls `confirm_or_exit` (default answer
  is No, declining exits 0) before `human_pause()` and `dx.api.execute()`. Do not add a write path
  that bypasses `run_write`.
- **`--dry-run` with `--channel-id` never contacts (or launches) Discord.** `run_write` previews
  `build(channel_id)` and returns before `connect(ctx)`. With `-g/-c` a dry run does connect to
  resolve names, but must still never execute the request.
- **The previewed request is the sent request.** Builders in `messages.py` return one `ApiRequest`;
  `preview(req)` and `dx.api.execute(req)` receive the same object.
- **Modules under `src/` import each other relatively** (`from .api import ApiCore`). The directory
  is `src/` but the import name is `dexport` (`package-dir` in `pyproject.toml`), so an absolute
  `from dexport.x import y` inside `src/` picks up the *installed* copy, not your working tree.
  A new sub-package under `src/` must also be added to `packages` in `pyproject.toml`;
  `tests/test_docs.py::test_pyproject_lists_every_subpackage` fails if you forget.
- **`session.py` is the only module that imports Playwright** (lazily, inside `Session.connect`).
  Everything else talks to the `Evaluator` / `RequestWatcher` protocols so it can be faked.

## Recipes

### Add a write verb (e.g. `pin`)

1. `src/messages.py`: add `pin_message_request(channel_id, message_id) -> ApiRequest` next to
   `delete_message_request`. Builders are pure and know the URL layout; nothing else does.
2. `tests/test_messages.py`: assert the builder's `method`, `path` and `body` (and `body_text()` if
   the body matters). This is the test that guards `--dry-run` output too.
3. `src/cli/write.py`: copy `delete`. Build a `Target(guild, channel, guild_id, channel_id)` and
   call `run_write(ctx, target, build=lambda cid: ..., confirm="Pin message ...", done=..., yes=yes,
   dry_run=dry_run)`. Reuse `YesOpt`, `DryRunOpt` and the target option aliases from `cli/common.py`.
4. README: add the row to the command reference table and an example under "Write"; CHANGELOG entry.

### Add a read command

1. If it needs a new endpoint, add a `*_request` builder (and a pager like `fetch_history` if it
   paginates) in `src/messages.py`; guild/channel listing belongs in `resolver.py`.
2. `src/cli/read.py`: `with connect(ctx) as dx:` fetch inside the block, print after it with
   `console` (rendering happens after the session is released). Resolve targets with
   `resolve_channel(dx, Target(...))` or `resolve_guild(dx, guild, guild_id)`.
3. Test the fetch/paging logic against `FakeApi` (`api.queue(200, payload)`, then inspect `api.calls`).
4. README command table + CHANGELOG.

### Add an export format

1. `src/render.py`: write `to_<fmt>(messages, title=None) -> str` using `oldest_first` and the
   shared helpers (`display_name`, `format_timestamp`, `attachment_lines`, `reaction_summary`).
2. Register it in `EXPORTERS` (keys are matched lower-case) and `EXPORT_EXTENSIONS`;
   `get_exporter` / `export_to_file` / `default_export_path` pick it up automatically.
3. `tests/test_render.py`: assert chronological order and that attachments/reactions appear.
4. Update the `--format` help text in `cli/read.py::export` and the README "Export" section.

### Add a config key

1. `src/config.py`: add a field with a default to `Settings` and a `_coerce(...)` line in
   `Settings.from_dict`. Field name == JSON key, so choose it carefully; it is permanent.
2. Env var: add an `ENV_*` constant and a branch in `Settings.with_env_overrides`.
3. CLI flag (only if it is a connection-level option): add it to `Settings.with_overrides`,
   `ConnectionOptions` + `ConnectionOptions.settings()` in `cli/common.py`, and the root callback in
   `cli/app.py`. User-settable keys also get an option in `cli/configure.py`.
4. Consume it in `client.py::Dexport.acquire` (that is where `Settings` turns into objects).
5. Update the expected dict in `test_settings_roundtrip_preserves_json_keys`, the README
   configuration table, and CHANGELOG.

## Commit hygiene

- Small, single-purpose PRs; `make check` green on every commit.
- Add a line to `CHANGELOG.md` for anything user-visible (new flag, changed output, new config key).
- If you touch a command or config key, update the README tables in the same commit -
  `tests/test_docs.py` will fail otherwise.
- Do not run `ruff format` over files you did not change; keep diffs reviewable.
- Commit with the email your GitHub account publishes. If you use GitHub's private-email
  setting, that is your `<id>+<user>@users.noreply.github.com` address.

## A note on scope

Automating a user account is against Discord's Terms of Service (see the README warning).
Keep new automation conservative: no bulk/loop verbs, no bypassing `confirm_or_exit` or
`human_pause`, no lowering the `RateLimiter` floor defaults, and nothing that reads or stores data
beyond the user's own view.

## Reporting a security problem

Do not open a public issue. Report it privately via
[GitHub Security Advisories](https://github.com/Patruxs/dexport/security/advisories/new);
[SECURITY.md](SECURITY.md) has the details, including what dexport does with the session
headers and which sharp edges are working as intended rather than bugs.
