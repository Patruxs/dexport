# dexport

[![CI](https://github.com/Patruxs/dexport/actions/workflows/ci.yml/badge.svg)](https://github.com/Patruxs/dexport/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-2a6db2)](https://mypy-lang.org/)
[![Linted with ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Drive **your own** Discord session from the command line — read, export, and
send messages without a bot token.

`dexport` doesn't use a bot token and it doesn't log in with your password.
Instead it attaches to the **Discord desktop client you already have open**
over the Chrome DevTools Protocol (CDP), snapshots the client's real request
headers once, and then makes Discord API calls with an in-page `fetch`.
Because the fetch runs inside Discord's own renderer, requests are
same-origin and carry the client's real header cluster (`X-Super-Properties`,
`X-Discord-Locale`, …). That is a *maintenance* decision, not a stealth one:
those headers encode the client build, so reconstructing them by hand would
mean tracking Discord's releases forever, and getting them wrong is a good way
to have requests rejected or the session invalidated. Borrowing the live ones
means every call is well-formed and your login keeps working. Nothing is
forged and no header is invented — they are your own client's, sent from your
own client.

> [!CAUTION]
> **Using this tool can get your Discord account permanently deleted.**
> Automating a **user** account (a "self-bot") is against Discord's Terms of
> Service, and the stated penalty is account termination — permanent, with no
> practical appeal, and Discord's one-account-per-person rule means you are
> not supposed to simply make a new one. dexport paces itself and respects
> rate limits, but pacing is not permission: a well-behaved self-bot is still
> a self-bot. There is no safe amount of this; there is only less risk and
> more risk.
>
> This tool is meant for personal, low-volume use on **your own** account and
> data — e.g. exporting your own DM history, or scripting the occasional
> message. Read [What you're risking](#what-youre-risking) before you run it.
> Everything you do with dexport, you do at your own risk; the MIT licence
> means there is no warranty and no liability, and the author cannot recover a
> terminated account for you.
>
> dexport prints this warning once, the first time it drives your account, and
> keeps a short version in `dexport --help`.

## Contents

- [How it works](#how-it-works)
- [What you're risking](#what-youre-risking)
- [Requirements](#requirements)
- [Install](#install)
- [Updating](#updating)
- [First run](#first-run)
- [Usage](#usage)
- [Configuration](#configuration)
- [Rate limiting & safety](#rate-limiting--safety)
- [Project layout](#project-layout)
- [Development](#development)
- [Contributing & security](#contributing--security)
- [License](#license)

## How it works

```
launcher  ──►  session/attach  ──►  header snapshot  ──►  api core + rate limiter  ──►  resolver  ──►  commands
(is the CDP    (connect over        (grab the first      (in-page fetch, X-RateLimit    (name → ID,    (read/export/
 port alive?    CDP, find the        authorized           aware, 429 retry)              cached,        send/reply/
 else launch    discord.com page)    /api/v9 request)                                    diacritics)    react)
 Discord with
 the debug flag)
```

Nothing sensitive is written to disk. The authorization header lives only in
memory for the duration of a single command. `~/.dexport/` holds just
`config.json`, a resolver cache (`cache.json`, guild/channel names ↔ IDs) and
`notice-shown` (the marker for the one-time warning above) — never credentials
or headers. The full account of what dexport does with your session is in
[SECURITY.md](SECURITY.md).

## What you're risking

Short version: an irreversible account loss, a locally exposed Discord
session, and irreversible writes to other people's conversations. In detail:

### 1. Your account — the big one

- **Permanent termination.** Self-botting is enforced as a terms violation,
  not a warning-first offence. If it happens you lose the account itself and
  everything attached to it: DM history, friends, Nitro time you paid for,
  purchased games and cosmetics, and any server you own (a deleted owner
  account can take the server with it or leave it stranded).
- **You cannot buy your way back.** Nitro does not protect an account, and a
  terminated account is not restored on request. Ban appeals for self-botting
  are rarely granted.
- **Softer punishments happen first, sometimes.** A flagged session can be
  invalidated (you get logged out everywhere), locked behind a phone/CAPTCHA
  verification, or temporarily blocked from the API. Treat any of these as the
  warning shot it is — stop, don't retry harder.
- **dexport does not hide you and does not try to.** The header snapshot
  exists so requests stay *well-formed* as the Discord client build changes —
  it is a correctness measure, not an evasion measure. Nothing in this tool
  claims or attempts to make automation undetectable, and no rate limit
  setting makes automated use permitted.
- **Risk scales with what you do.** Reading your own DM history once is at one
  end; unattended loops, cron jobs, mass deletion, bulk reacting, scraping
  servers you don't own, or anything that resembles a bot service, are at the
  other. Do not run dexport on an account you cannot afford to lose.

### 2. Your machine — the debug port

- dexport needs Discord running with `--remote-debugging-port`. **That port is
  unauthenticated by design.** While it is open, any process on your machine
  that can reach `127.0.0.1:<port>` gets full control of the Discord renderer:
  it can read your messages, send messages as you, and read your session
  token. This is a property of the Chrome DevTools Protocol, not a dexport
  bug.
- Never forward, tunnel, or expose that port (no `ssh -R`, no `0.0.0.0`
  binding, no container port publishing). Don't use dexport on a shared or
  untrusted machine, or one you don't administer.
- The port stays open for as long as that Discord process lives — not just
  while a dexport command runs. **Quit and reopen Discord normally when you're
  done** if you want it closed.
- `--restart` kills the running Discord client (SIGTERM, then SIGKILL). Any
  unsent message draft is lost and you drop out of a voice/video call.

### 3. Your conversations — writes are real and irreversible

- `send`, `reply`, `react`, `edit` and `delete` hit the live Discord API.
  Nothing is sandboxed. A deleted message is gone, an edit is visible to
  everyone as "(edited)", and other people (and their notifications) see
  everything instantly.
- Channel names are matched **fuzzily**, so a typo can resolve to a channel
  you did not mean — a message meant for a private server can land in a public
  one. Preview with `--dry-run` first, and use `--channel-id` in scripts:
  with an explicit ID the fuzzy resolver is not consulted at all.
- `--yes` removes the confirmation prompt and the last thing standing between
  a wrong flag and a public mistake. Don't use it in loops you aren't watching.

### 4. Other people's data — exports are not yours to spread

- An export of a channel contains other members' messages, names and IDs. In
  many jurisdictions that makes you responsible for how it is stored and
  shared, and most servers' rules forbid republishing their content. Exporting
  a server you don't own can get you banned from that server even if Discord
  itself never notices.
- Export files land in plain text where you point `-o`; treat them like any
  other dump of private conversation. dexport itself stores no credentials
  (see [SECURITY.md](SECURITY.md)), but it will happily write a channel's
  entire history to a file you then forget about.

### Using it with the least risk

- Your own account, your own DMs and servers; ask before exporting anyone
  else's.
- Low volume, attended runs. No cron, no unattended loops, no bulk
  delete/react sweeps.
- Leave `floor_delay_min` / `floor_delay_max` at their defaults or raise them;
  never lower them.
- `--dry-run` before any write, `--channel-id` in anything scripted.
- Close the debug port when you're done: quit Discord and reopen it normally.
- If Discord logs you out, shows a CAPTCHA, or starts returning `429`s —
  stop for the day rather than retrying.

## Requirements

- Python 3.11+
- The Discord desktop client (Windows, macOS, or Linux — including Flatpak)
  installed and logged in
- Discord PTB / Canary are also detected on Linux

You do **not** need to run `playwright install` — dexport connects to
Discord's existing Electron process rather than launching its own browser.

## Install

dexport is not on PyPI; install it from the repository:

```bash
pipx install git+https://github.com/Patruxs/dexport
# or, from a local checkout:
pipx install .
# or, for development (editable):
pip install -e ".[dev]"
```

`pipx` itself comes from `pip install --user pipx`; run `pipx ensurepath` once
afterwards so the installed `dexport` command is on your `PATH`. Plain
`pip install git+https://github.com/Patruxs/dexport` works too — pipx is only
recommended because it keeps dexport and its dependencies in their own venv.

## Updating

```bash
pipx upgrade dexport                                           # released versions
pipx install --force git+https://github.com/Patruxs/dexport    # any commit on main
```

`pipx upgrade` compares *version numbers*, so it moves you from one release to
the next but reports `already at latest version` for commits pushed since — the
`--force` form (or `pipx reinstall dexport`) re-fetches the repository and is
the one to use when you want the current `main`.

Development installs need no reinstall: `git pull` is enough, because
`pip install -e` points at your working tree. Re-run `pip install -e ".[dev]"`
only when the dependencies or the `packages` list in `pyproject.toml` change.

## First run

dexport needs the Discord desktop client to expose a CDP port. If it isn't
already, dexport will try to launch Discord with `--remote-debugging-port`.
Because Discord uses a single-instance lock, an already-open client started
*without* that flag can't be upgraded in place — so either fully quit Discord
first, or let dexport restart it for you:

```bash
dexport --restart whoami
```

If it prints your account, the foundation works:

```
Logged in as YourName (@yourname)  (123456789012345678)
```

You can pin the port and binary so future runs are frictionless:

```bash
dexport configure --port 9222 --binary /opt/discord/Discord --show
```

## Usage

Connection flags (`--port`, `--restart`, `--binary`) are **global** — they go
before the sub-command:

```bash
dexport [--port 9222] [--restart] [--binary /path/to/Discord] <command> [options]
```

`dexport --version` prints the installed version and exits.

### Read

```bash
dexport whoami
dexport guilds
dexport channels -g "my server"
dexport read     -g "my server" -c "general" --limit 100
```

### Export (Markdown or JSON)

```bash
dexport export -g "my server" -c "general" --format md -o out.md
dexport export --channel-id 123456789012345678 -f json -o out.json
```

### Write

Write commands ask for confirmation by default, add a short human-like pause
before acting, and support `--dry-run` to preview the exact HTTP request
without sending anything.

```bash
dexport send   -g "my server" -c "general" -m "hello!"
dexport reply  -g "my server" -c "general" --to <message_id> -m "replying"
dexport react  -g "my server" -c "general" --to <message_id> -e 👍
dexport edit   --channel-id <channel_id> --to <message_id> -m "edited text"
dexport delete --channel-id <channel_id> --to <message_id>

dexport send -g "my server" -c "general" -m "hi" --yes       # skip confirmation
dexport send -g "my server" -c "general" -m "hi" --dry-run   # preview only
```

### Command reference

| Command | Purpose |
| --- | --- |
| `whoami` | Verify the session; prints your account. |
| `guilds` | List servers your account is in. |
| `channels` | List channels in a server. |
| `read` | Print recent messages from a channel. |
| `export` | Export channel history to a Markdown or JSON file. |
| `send` | Send a message to a channel. |
| `reply` | Reply to a specific message. |
| `react` | Add a reaction (unicode emoji or `name:id`) to a message. |
| `edit` | Edit one of your own messages. |
| `delete` | Delete a message. |
| `configure` | View or update `~/.dexport/config.json`. |

Run `dexport <command> --help` for the full option list of any command.

Guild/channel names are matched diacritics-insensitively and fuzzily, so
`-g "cu dem"` finds `cú đêm`. For scripting, pass `--guild-id` /
`--channel-id` to skip the fuzzy lookup and avoid any matching ambiguity;
with `--channel-id` the resolver is not consulted at all.

## Configuration

Settings are resolved in this order: CLI flag > environment variable >
`~/.dexport/config.json` > built-in default.

| Config key | Env var | CLI flag | Default | Meaning |
| --- | --- | --- | --- | --- |
| `port` | `DEXPORT_PORT` | `--port` | `9222` | CDP port Discord exposes. |
| `discord_binary` | `DEXPORT_DISCORD_BINARY` | `--binary` | auto-detected | Path to the Discord executable. |
| `floor_delay_min` | — | — | `0.25` | Self-imposed delay window (seconds) before every request — lower bound. |
| `floor_delay_max` | — | — | `0.6` | Self-imposed delay window (seconds) before every request — upper bound. |
| — | `DEXPORT_HOME` | — | `~/.dexport` | Where config/cache are stored. |

`dexport configure --port 9222 --binary /path/to/Discord` writes these to
`~/.dexport/config.json`. `dexport configure --show` prints the stored config
with defaults filled in (environment overrides are deliberately *not* applied,
so they can never be written back to the file). `floor_delay_min` /
`floor_delay_max` have no flag or env var — edit them in `config.json`
directly.

## Rate limiting & safety

- A self-imposed floor delay (250–600 ms + jitter) before every request. The
  window is configurable via `floor_delay_min` / `floor_delay_max` in
  `config.json`.
- Reads `X-RateLimit-Remaining` / `X-RateLimit-Reset-After` per route and
  sleeps before a route runs dry.
- On `429`, honours `retry_after` (global limits back off across all routes).
- Write commands add an extra human-like pause and confirm before acting
  unless `--yes` is passed.

The exact limiter and retry rules are spelled out in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#rate-limiting-and-retries).

## Project layout

The package lives in `src/` and is imported as `dexport`:

```
.                     # repo root
├── pyproject.toml    # name = "dexport", entry point, tool config
├── tests/  docs/  Makefile  README.md
└── src/              # the package — imported as `dexport`, modules below
    ├── api.py  session.py  ...
    ├── cli/
    └── launcher/
```

`pyproject.toml` maps the directory onto the import name with
`package-dir = { "dexport" = "src" }`, so `import dexport` and the built wheel
(which ships a normal `dexport/` package) are unaffected. Two consequences for
contributors: `packages` in `pyproject.toml` is hand-maintained because
auto-discovery cannot see through the rename, and modules must use **relative**
imports (`from .api import ApiCore`) — an absolute `from dexport.api import ...`
inside `src/` resolves to the installed copy, not your working tree.

| Module | Responsibility |
| --- | --- |
| `launcher/` | Is the CDP port alive? Else find Discord and launch it with the debug flag, then poll the port. `discovery.py` locates the binary per OS (stable/PTB/Canary, Flatpak); `process.py` starts, finds and kills the process. |
| `session.py` | Attach over CDP, pick the real app page. The *only* module that touches Playwright. |
| `headers.py` | Snapshot the client's authorized headers (RAM only) and sanitise them for `fetch`. |
| `ratelimit.py` | Per-route limiter: floor delay, `X-RateLimit-*` bookkeeping, 429 handling. |
| `api.py` | In-page `fetch` core + retries — the heart. `ApiRequest` in, `ApiResponse` out. |
| `resolver.py` | Name → ID with cache and diacritics-aware matching. |
| `messages.py` | History pagination and the send/reply/react/edit/delete request builders (was `service.py`). |
| `render.py` | Terminal output + Markdown/JSON export (`EXPORTERS`). |
| `client.py` | Wires the whole pipeline into `Dexport.acquire()`. |
| `cli/` | Typer command surface: `app.py` (root + global flags), `common.py` (shared plumbing, `run_write`), `read.py`, `write.py`, `configure.py`. |
| `config.py` | `Settings` ↔ `config.json`, the resolver cache file, `DEXPORT_HOME` paths. |
| `models.py` | `ChannelType`, `MESSAGE_CHANNEL_TYPES`, and the `GuildRef`/`ChannelRef` cache shapes. |
| `errors.py` | The `DexportError` hierarchy the CLI turns into one-line errors. |
| `util.py` | Pure helpers: diacritics stripping, `normalize`, `is_snowflake`, `human_bytes`. |

`python -m dexport` works as well as the `dexport` entry point.

## Development

```bash
make install    # or: pip install -e ".[dev]"
make check      # ruff check + ruff format --check + mypy (strict) + pytest
```

`make check` is exactly what CI runs. The individual targets are `make test`,
`make lint`, `make fmt` (auto-fix and format) and `make typecheck`; `make help`
lists them. Every target uses `./.venv` when it exists, so there is nothing to
activate.

The tests are fully offline. The pure/core logic (normalisation, rate-limiter
math, emoji encoding, header sanitising, the API retry state machine via a
fake session) is covered without a running Discord client, and an autouse
fixture points `DEXPORT_HOME` at a temp dir so your real `~/.dexport` is never
touched.

To smoke-test against a live client after a change:

```bash
dexport --restart whoami                                # whole pipeline: launch → attach → snapshot → GET /users/@me
dexport send --channel-id <channel_id> -m hi --dry-run  # builds and previews a write; contacts nothing
```

How the pieces fit together — and how to add a command, an export format or
a config key — is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The
contribution workflow is in [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing & security

Contributions are welcome — open an [issue](https://github.com/Patruxs/dexport/issues)
or a pull request. Please keep the scope of automation features conservative
given the ToS caveat above; the workflow and the review checklist are in
[CONTRIBUTING.md](CONTRIBUTING.md).

Found a security problem? **Don't open a public issue** — report it privately
via [GitHub Security Advisories](https://github.com/Patruxs/dexport/security/advisories/new).
[SECURITY.md](SECURITY.md) also documents exactly what dexport does with your
session headers, and which sharp edges (the unauthenticated CDP port, most of
all) are working as intended.

## License

MIT — see [LICENSE](LICENSE).
