# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-28

### Added

- npm packaging: `npm install -g dexport` installs the CLI for people who do not
  have a Python toolchain to hand. The wrapper in `npm/` builds a private
  virtualenv inside the installed package and pip-installs the shipped sources
  into it; `DEXPORT_PYTHON` overrides interpreter discovery. pipx/pip installs
  are unchanged.

- `install-agent` — writes a `/dexport` slash command and an
  [Agent Skill](https://agentskills.io) for the coding agents it finds (Claude
  Code, Codex CLI, Cursor, Gemini CLI, opencode, pi), each in that tool's own
  format and location. The skill is what the agent loads by itself the moment
  a question is about Discord, so plain language works; `/dexport <question>`
  stays as the explicit path. `--target` picks agents explicitly, `--project`
  installs into the working directory, `--print` dumps the text for anything
  else. The generated command and skill are read-only: they allow
  `guilds`/`channels`/`export` and forbid every write verb.

- `configure --launch-timeout` / `DEXPORT_LAUNCH_TIMEOUT` — how long to wait
  for a launched Discord client to open its debug port before giving up
  (default 90s).

## [0.1.0] - 2026-08-26

First public release. `dexport` drives the user's own Discord desktop client
over CDP: it attaches to the running client, snapshots its authorized request
headers into memory, and issues `/api/v9` calls with an in-page `fetch`. No bot
token, no password, nothing sensitive on disk.

### Added

- Read commands: `whoami`, `guilds`, `channels`, `read`.
- `export` — channel history to Markdown or JSON, always oldest-first.
- Write commands: `send`, `reply`, `react`, `edit`, `delete`. Every one of them
  confirms before acting (unless `--yes`), adds a short human-like pause, and
  supports `--dry-run` to print the exact request that would be sent — built by
  the same code that sends it, so the preview cannot drift.
- `configure` — view or update `~/.dexport/config.json`.
- `dexport --version`.
- A per-route rate limiter: a self-imposed floor delay with jitter,
  `X-RateLimit-*` bookkeeping, and `429` `retry_after` handling that backs off
  globally when the limit is global.
- Name → ID resolution that is fuzzy and diacritics-insensitive (`-g "cafe"`
  finds `café`), cached in `~/.dexport/cache.json`, with `--guild-id` /
  `--channel-id` to bypass it entirely for scripting.
- Discord discovery and launch on Windows, macOS and Linux — including Flatpak,
  PTB and Canary — with `--restart` to work around the single-instance lock.
- A one-time Terms-of-Service notice on the first run that actually drives the
  account, plus a condensed warning in `dexport --help`, so the caveat reaches
  people who installed with `pipx` and never opened the README.
- Documentation: `README.md`, `docs/ARCHITECTURE.md`, `CONTRIBUTING.md`,
  `SECURITY.md` (which spells out that headers live in RAM only, and which
  sharp edges are working as intended), and this changelog.
- Project infrastructure: MIT `LICENSE`, GitHub Actions CI across Python
  3.11–3.14, `ruff` (lint + format) and `mypy --strict` configuration that the
  code base passes, a `Makefile` (`install` / `test` / `lint` / `fmt` /
  `typecheck` / `check`), an optional `.pre-commit-config.yaml`, Dependabot,
  and issue / pull-request templates.
- A fully offline test suite: shared fixtures in `tests/conftest.py` (fake
  session, fake API, no-sleep limiter) and an autouse fixture that points
  `DEXPORT_HOME` at a temp directory so a real `~/.dexport` is never touched.

### Notes for anyone who cloned before this tag

The repository was public for a few hours before `v0.1.0` was cut. If you
pulled in that window, these are the changes since the initial commit.

- The package moved into `src/`: what was `dexport/` is now `src/`, mapped onto
  the import name by `package-dir = { "dexport" = "src" }`. Nothing changes for
  users — `import dexport`, the `dexport` entry point and the published wheel
  (which still ships a normal `dexport/` package) are identical. Contributors
  must re-run `pip install -e ".[dev]"` after pulling, because the editable
  install points at the old directory.
- The build backend switched from hatchling to setuptools. Hatchling refuses
  editable installs when a `sources` rewrite *renames* a prefix rather than
  removing it, which the layout above requires; setuptools supports it via
  `package-dir`. Consequences: `packages` is now listed explicitly in
  `pyproject.toml` (auto-discovery cannot see through the rename, so
  `test_pyproject_lists_every_subpackage` guards it), the version is read with
  `[tool.setuptools.dynamic] version = { attr = ... }`, and the license
  metadata moved to the PEP 639 form (`license = "MIT"` plus `license-files`,
  with the now-forbidden `License ::` classifier dropped).
- Internal refactor for maintainability: `cli.py` and `launcher.py` became the
  `cli/` and `launcher/` packages, `service.py` became `messages.py`, new
  `models.py`, `config.py` gained a typed `Settings`, and the write path now
  builds one `ApiRequest` that is both previewed and sent. The user-visible
  differences are, exhaustively:
  - `--help` output is richer: every option on every command now has a
    description (previously `-g`, `-c`, `--guild-id`, `--channel-id`, `--yes`,
    `--dry-run`, `-m` and `--limit` were undocumented on several commands).
  - `reply --dry-run` now shows `"fail_if_not_exists": false` inside
    `message_reference`. It was already being sent; the preview simply used
    to omit it.
  - When a `401` triggers an automatic header re-capture and that re-capture
    itself fails, the error message now says so instead of reporting a bare
    `401`.
  - `dexport configure` re-saves `config.json` with exactly the four known
    keys (`port`, `discord_binary`, `floor_delay_min`, `floor_delay_max`); any
    unrecognised keys in an existing file are dropped on the next save, and a
    malformed value now falls back to its default instead of crashing.
  - `export --format <unknown>` still fails with `error: Unknown export
    format: ...`, but the hint now reads `(use one of: json, markdown, md)`
    instead of `(use 'md' or 'json')`, and the check happens *before* Discord
    is launched/attached (previously the whole history was fetched first).
  - `--port 0` is now passed through as given (it used to fall back to the
    configured port); an explicit CLI value always wins.
- Python API (importable, but not covered by any stability promise):
  `Dexport.acquire(settings=, force_restart=, paths=)` replaces
  `acquire(port=, force_restart=, binary_override=)`; `ApiCore.request(...,
  raise_for_status=True)` replaces `expect_json=`; the `service.send_message`
  / `edit_message` / `delete_message` / `add_reaction` / `remove_reaction`
  functions are now `messages.*_request` builders executed via
  `ApiCore.execute`.
- Fixed: an account that is in zero guilds now caches the empty list instead of
  refetching `/users/@me/guilds` on every invocation.

[Unreleased]: https://github.com/Patruxs/dexport/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Patruxs/dexport/releases/tag/v0.1.0
