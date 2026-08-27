# dexport

[![CI](https://github.com/Patruxs/dexport/actions/workflows/ci.yml/badge.svg)](https://github.com/Patruxs/dexport/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Drive **your own** Discord session from the command line — read, export and
send messages without a bot token.

dexport attaches to the Discord desktop client you already have open over the
Chrome DevTools Protocol, snapshots its real request headers once, and calls
`/api/v9` with an in-page `fetch`. Reusing the live headers is a *correctness*
choice, not a stealth one: they encode the client build, so hand-rolling them
would mean tracking every Discord release. Nothing is forged — they are your
own client's headers, sent from your own client.

> [!CAUTION]
> **This can get your Discord account permanently deleted.** Automating a user
> account (a "self-bot") is against Discord's Terms of Service, and the penalty
> is permanent termination. dexport paces itself and respects rate limits, but
> pacing is not permission. Keep it personal, low-volume, and on your own
> account and data — and read [What you're risking](#what-youre-risking)
> first. MIT means no warranty; a terminated account can't be recovered.
>
> The notice is printed once on first use and summarised in `dexport --help`.

## Contents

- [How it works](#how-it-works)
- [What you're risking](#what-youre-risking)
- [Install](#install)
- [First run](#first-run)
- [Usage](#usage)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Development](#development)
- [Contributing & security](#contributing--security)

## How it works

```
launcher  ──►  session/attach  ──►  header snapshot  ──►  api core + rate limiter  ──►  resolver  ──►  commands
(is the CDP    (connect over        (grab the first      (in-page fetch, X-RateLimit    (name → ID,    (read/export/
 port alive?    CDP, find the        authorized           aware, 429 retry)              cached,        send/reply/
 else launch    discord.com page)    /api/v9 request)                                    diacritics)    react)
 Discord with
 the debug flag)
```

Nothing sensitive touches disk: the authorization header lives in memory for
one command only. `~/.dexport/` holds `config.json`, a name ↔ ID cache
(`cache.json`) and the one-time-notice marker — never credentials.
[SECURITY.md](SECURITY.md) has the full account.

## What you're risking

- **Your account.** Termination for self-botting is permanent and takes
  everything with it: DMs, friends, Nitro you paid for, servers you own.
  Softer signals come first sometimes — a forced logout, a CAPTCHA/phone
  lock, a wall of `429`s; treat any of them as a stop sign. dexport does not
  hide you and does not try to. Risk scales with what you do: exporting your
  own DM history once is not a 24/7 loop.
- **The debug port.** Discord runs with `--remote-debugging-port`, which is
  unauthenticated by design — any local process that reaches it can read your
  messages, send as you, and take your session token. Never forward or expose
  it, don't use dexport on a shared machine, and quit Discord normally when
  you're done to close it. `--restart` kills the client outright (drafts lost,
  calls dropped).
- **Writes are real.** `send`/`edit`/`delete` hit the live API with no undo,
  and names are matched *fuzzily*, so a typo can land a message in the wrong
  channel. Preview with `--dry-run`, use `--channel-id` in scripts, and treat
  `--yes` as removing your last safety check.
- **Exports hold other people's messages.** Their names, IDs and content, in
  plain text where you point `-o`. Most servers' rules forbid republishing
  that, and exporting a server you don't own can get you banned from it.

Least risk: your own account and data, low volume, attended runs; leave the
delay floors alone; `--dry-run` before writes; stop for the day if Discord
logs you out or starts returning `429`s.

## Install

Requires Python 3.11+ and the Discord desktop client (Windows, macOS, Linux
including Flatpak; PTB/Canary are detected on Linux) installed and logged in.
You do **not** need `playwright install` — dexport attaches to Discord's own
Electron process.

```bash
pipx install git+https://github.com/Patruxs/dexport   # or: pip install -e ".[dev]"
dexport install-agent                                 # optional: adds /dexport
```

To update, use `pipx install --force git+...`: plain `pipx upgrade` only
compares version numbers, so it won't pick up new commits on `main`. Editable
installs just need `git pull`.

## First run

Discord holds a single-instance lock, so a client already running *without*
the debug flag can't be upgraded in place — quit it first, or let dexport
restart it for you:

```bash
dexport --restart whoami        # → Logged in as YourName (@yourname)
```

Then pin the port and binary so later runs are frictionless:

```bash
dexport configure --port 9222 --binary /opt/discord/Discord --show
```

## Usage

Connection flags are **global** — they go before the sub-command:

```bash
dexport [--port 9222] [--restart] [--binary /path/to/Discord] <command> [options]
```

### Read and export

```bash
dexport guilds
dexport channels -g "my server"
dexport read     -g "my server" -c "general" --limit 100
dexport export   -g "my server" -c "general" --format md -o out.md
dexport export   --channel-id 123456789012345678 -f json -o out.json
```

### Write

Write verbs confirm first, pause briefly, and accept `--dry-run` (preview the
exact request, send nothing) and `--yes` (skip the confirmation):

```bash
dexport send   -g "my server" -c "general" -m "hello!"
dexport reply  --channel-id <channel_id> --to <message_id> -m "replying"
dexport react  --channel-id <channel_id> --to <message_id> -e 👍
dexport edit   --channel-id <channel_id> --to <message_id> -m "edited text"
dexport delete --channel-id <channel_id> --to <message_id> --dry-run
```

Names are fuzzy and diacritics-insensitive (`-g "my serv"` finds `My Server`,
`-c "cafe"` finds `#café`); `--channel-id` skips the resolver entirely and is
what you want in scripts.

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
| `install-agent` | Write the `/dexport` slash command for your coding agent(s). |

`dexport <command> --help` has the full option list of any command.

### Just ask your agent instead

The nicest way to live with dexport is to never type a flag. Once, after
installing:

```bash
dexport install-agent
```

That writes a `/dexport` slash command into every coding agent it finds on your
machine — Claude Code, Codex CLI, Cursor, Gemini CLI, opencode — each in that
tool's own format and location. Restart the agent if it was open, and then you
just talk to it:

```
/dexport what did I miss in #general today?
/dexport summarise #team this week — who is waiting on a reply from me?
/dexport did Mai reply yesterday? draft an answer, I'll send it
```

You never look up an ID: the command teaches the agent to find the channel
itself with `dexport guilds` / `dexport channels`, export it to JSON, and
answer from that file.

| Flag | |
| --- | --- |
| `--target claude` | Install for specific agents instead of the detected ones; repeatable. |
| `--project` | Write into `./` (this repo) instead of your home directory. |
| `--force` | Overwrite a `/dexport` that is already there. |
| `--print` | Print the text instead of installing, for any tool not on the list: `dexport install-agent --print > ~/.wherever/dexport.md`. |

> [!CAUTION]
> The installed command is read-only *by construction* — it allows `guilds`,
> `channels` and `export`, and tells the agent never to send, reply, react,
> edit or delete. Keep it that way. Everything an agent reads was written by
> other people, so one that can read *and* write can be steered by anyone in
> the channel; a polite instruction is not a control, the allowlist is. And
> don't leave an agent polling on a timer — a bot service running on a user
> account is precisely what gets accounts terminated.

### Scripting notes

- Discord must be running and logged in the whole time — there is no headless
  mode. Run **one dexport at a time**: the rate limiter is per-process, so
  parallel invocations just double your request rate.
- Exit codes: `0` success (**and** when a confirmation is declined), `1`
  dexport error (`error: ...` on stderr), `2` usage error. A write without
  `--yes` in a non-interactive shell has no stdin to answer its prompt, so it
  aborts with exit 1 and sends nothing.
- Only `export -f json` is meant for parsing (raw message objects, oldest
  first). `read`/`guilds`/`channels` are Rich-formatted for a terminal, and
  `--dry-run` renders content as Rich markup — `[b]`/`[/]` in a message body
  are mangled in the *preview* only; the request itself is built correctly.
- For more than a couple of calls, acquire the session once instead of paying
  for an attach — and possibly a page reload — per invocation:

```python
from dexport.client import Dexport
from dexport.messages import fetch_history, send_message_request

with Dexport.acquire() as dx:
    history = fetch_history(dx.api, "123456789012345678", limit=200)
    dx.api.execute(send_message_request("123456789012345678", "hello"))
```

  That layer has no confirmation prompt and no human pause — those live in the
  CLI — but the rate limiter still applies.

## Configuration

Resolved as **CLI flag > environment variable > `~/.dexport/config.json` >
default**.

| Config key | Env var | CLI flag | Default | Meaning |
| --- | --- | --- | --- | --- |
| `port` | `DEXPORT_PORT` | `--port` | `9222` | CDP port Discord exposes. |
| `discord_binary` | `DEXPORT_DISCORD_BINARY` | `--binary` | auto-detected | Path to the Discord executable. |
| `floor_delay_min` | — | — | `0.25` | Self-imposed delay before every request — lower bound (seconds). |
| `floor_delay_max` | — | — | `0.6` | Self-imposed delay before every request — upper bound (seconds). |
| — | `DEXPORT_HOME` | — | `~/.dexport` | Where config and cache are stored. |

`dexport configure --show` prints the stored file with defaults filled in;
environment overrides are deliberately not applied, so they can never be
written back. The delay floors have no flag or env var — edit `config.json`.
On top of them, dexport tracks `X-RateLimit-*` per route, sleeps before a
route runs dry, and honours `retry_after` on `429`; the exact rules are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#rate-limiting-and-retries).

## Project layout

The package lives in `src/` and is imported as `dexport`
(`package-dir = { "dexport" = "src" }`). Two consequences: `packages` in
`pyproject.toml` is hand-maintained, and modules inside `src/` must use
relative imports.

| Module | Responsibility |
| --- | --- |
| `launcher/` | Is the CDP port alive? Else find Discord and launch it with the debug flag. `discovery.py` locates the binary per OS; `process.py` starts/finds/kills it. |
| `session.py` | Attach over CDP, pick the real app page. The *only* module that touches Playwright. |
| `headers.py` | Snapshot the client's authorized headers (RAM only) and sanitise them for `fetch`. |
| `ratelimit.py` | Per-route limiter: floor delay, `X-RateLimit-*` bookkeeping, 429 handling. |
| `api.py` | In-page `fetch` core + retries. `ApiRequest` in, `ApiResponse` out. |
| `resolver.py` | Name → ID with cache and diacritics-aware matching. |
| `messages.py` | History pagination and the send/reply/react/edit/delete request builders. |
| `render.py` | Terminal output + Markdown/JSON export (`EXPORTERS`). |
| `client.py` | Wires the pipeline into `Dexport.acquire()`. |
| `cli/` | Typer surface: `app.py` (root + global flags), `common.py` (`run_write` and friends), `read.py`, `write.py`, `configure.py`. |
| `config.py` | `Settings` ↔ `config.json`, the resolver cache file, `DEXPORT_HOME` paths. |
| `models.py` | `ChannelType`, `MESSAGE_CHANNEL_TYPES`, the `GuildRef`/`ChannelRef` cache shapes. |
| `errors.py` | The `DexportError` hierarchy the CLI turns into one-line errors. |
| `agents.py` | The `/dexport` slash command: one prompt, rendered per agent tool. |
| `util.py` | Pure helpers: diacritics stripping, `normalize`, `is_snowflake`, `human_bytes`. |

## Development

```bash
make install    # or: pip install -e ".[dev]"
make check      # ruff check + ruff format --check + mypy (strict) + pytest — what CI runs
```

Individual targets: `make test`, `make lint`, `make fmt`, `make typecheck`.
The tests are fully offline and an autouse fixture points `DEXPORT_HOME` at a
temp dir, so your real `~/.dexport` is never touched. To smoke-test against a
live client, `dexport --restart whoami` exercises the whole pipeline.

How the pieces fit together — and how to add a command, an export format or a
config key — is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); the workflow
is in [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing & security

Issues and pull requests welcome — please keep the scope of automation
features conservative given the caveat above.

Found a security problem? **Don't open a public issue** — use
[GitHub Security Advisories](https://github.com/Patruxs/dexport/security/advisories/new).
[SECURITY.md](SECURITY.md) documents what dexport does with your session
headers and which sharp edges are working as intended.

## License

MIT — see [LICENSE](LICENSE).
