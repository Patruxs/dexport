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

> [!WARNING]
> Automating a **user** account (a "self-bot") is against Discord's Terms of
> Service, and the penalty is account termination — permanent. This tool is
> meant for personal, low-volume use on your own account and data — e.g.
> exporting your own DM/channel history, or scripting the occasional message.
> It deliberately paces itself and respects rate limits, but that does not
> make automation allowed. Use at your own risk.
>
> dexport prints this warning once, the first time it drives your account, and
> keeps a short version in `dexport --help`.

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Install](#install)
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
