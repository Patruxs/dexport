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

> [!IMPORTANT]
> **The Discord desktop client has to be open and logged in for dexport to
> work** — every command, including the ones your coding agent runs. There is
> no headless mode and no token login; dexport only drives the client that is
> already running on your machine. If nothing is running, dexport launches
> Discord itself with the debug flag; if a client is *already* open without
> that flag, restart it with `dexport --restart <command>`. Quit Discord and
> dexport stops working until you open it again.

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

Requires Python 3.11+ (plus Node 18+ if you install with npm) and the Discord
desktop client (Windows, macOS, Linux including Flatpak; PTB/Canary are
detected on Linux) installed and logged in.
You do **not** need `playwright install` — dexport attaches to Discord's own
Electron process.

```bash
npm install -g dexport   # or: npm install -g github:Patruxs/dexport
dexport install-agent    # optional: teaches your coding agent
```

### Clean install

Two symptoms mean you are running a dexport you did not think you installed:
`dexport --version` disagrees with what you just installed, or an error quotes
timings and wording that are nowhere in the current source. Both come from the
same thing — more than one copy on `PATH`, and the first one wins, which is not
necessarily the one you upgraded. An npm global next to a `pipx` install does
it, and so does `pipx upgrade` deciding there is nothing to do because the
version number never moved.

Remove every copy, then install exactly one:

```bash
which -a dexport            # Windows: where dexport
                            # more than one line is the whole problem
npm uninstall -g dexport

npm install -g dexport      # or: npm install -g github:Patruxs/dexport
hash -r                     # bash caches resolved paths — without this your
                            # shell keeps calling the binary you just deleted
dexport --version           # must be the version you meant to install
```

Ignore "not installed" complaints from the uninstall lines; they are there to
catch whichever installer you actually used.

Then put the agent files back. Uninstalling never touches them, and they are
*not* refreshed by an upgrade either, because nothing is overwritten silently:

```bash
dexport install-agent --force
```

`~/.dexport/` survives all of this on purpose — `config.json`, the name ↔ ID
cache and the notice marker are not tied to any version. Delete the directory
as well if you want the first-run experience back, including the one-time
notice.

If commands still fail after that, the install is fine and the problem is on
the Discord side. `dexport --restart guilds` is the one to try: a client that
was started normally has no debug port, and Discord's single-instance lock
means a second launch is handed to it rather than replacing it, so dexport
cannot attach until that client is actually gone. Run it yourself rather than
through an agent — it kills the running client, drafts and calls included.


## Usage

### Just ask your agent instead

The nicest way to live with dexport is to never type a flag:

```bash
dexport install-agent
```

This teaches every coding agent on your machine — Claude Code, Codex CLI,
Cursor, Gemini CLI, opencode, pi — how to use dexport: an
[Agent Skill](https://agentskills.io) it loads by itself for Discord
questions, plus a `/dexport` slash command for when you want to be explicit.
Restart the agent if it was already open.

```
/dexport what did I miss in #general today?
/dexport did Mai reply yesterday? draft an answer, I'll send it
```

Plain language works whenever the agent recognizes the question is about
Discord and picks the skill up by itself. `/dexport` is the explicit form —
use it any time, and especially when an agent answers from somewhere else (a
web search, say) instead of your Discord, since that means it missed the
skill and the prefix forces it through dexport instead.

Keep the Discord desktop client open and logged in — nothing works without it.

| Agent | Skill | Command |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/dexport/` | `~/.claude/commands/dexport.md` |
| Codex CLI | `~/.agents/skills/dexport/` | `~/.codex/prompts/dexport.md` |
| Cursor | `~/.cursor/skills/dexport/` | `~/.cursor/commands/dexport.md` |
| Gemini CLI | `~/.gemini/skills/dexport/` | `~/.gemini/commands/dexport.toml` |
| opencode | `~/.config/opencode/skills/dexport/` | `~/.config/opencode/command/dexport.md` |
| pi | `~/.pi/agent/skills/dexport/` | `~/.pi/agent/prompts/dexport.md` |

Codex is the odd one: it has no `~/.codex/skills`, and reads the vendor-neutral
`~/.agents/skills` instead — which Cursor, Gemini CLI, opencode and pi also
honour.

You never look up an ID either: the instructions teach the agent to find the
channel itself with `dexport guilds` / `dexport channels`, export it to JSON,
and answer from that file.

| Flag | |
| --- | --- |
| `--target claude` | Install for specific agents instead of the detected ones; repeatable. |
| `--project` | Write into `./` (this repo) instead of your home directory. |
| `--force` | Overwrite instructions that are already there. Needed when upgrading dexport, since nothing is replaced silently. |
| `--print` | Print the text instead of installing, for any tool not on the list: `dexport install-agent --print > ~/.wherever/dexport.md`. |

> [!CAUTION]
> The installed instructions are read-only by design — they tell the agent
> never to send, reply, react, edit or delete, and the `allowed-tools` grant
> covers only `guilds`, `channels` and `export`, so a write verb always stops
> at a permission prompt instead of running unattended. Keep them that way. Everything an agent reads was
> written by other people, so one that can read *and* write can be steered by
> anyone in the channel; a polite instruction is not a control, the allowlist is. And
> don't leave an agent polling on a timer — a bot service running on a user
> account is precisely what gets accounts terminated.


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
| `install-agent` | Teach your coding agent(s) how to read Discord with dexport. |

`dexport <command> --help` has the full option list of any command.

## Configuration

Resolved as **CLI flag > environment variable > `~/.dexport/config.json` >
default**.

| Config key | Env var | CLI flag | Default | Meaning |
| --- | --- | --- | --- | --- |
| `port` | `DEXPORT_PORT` | `--port` | `9222` | CDP port Discord exposes. |
| `discord_binary` | `DEXPORT_DISCORD_BINARY` | `--binary` | auto-detected | Path to the Discord executable. |
| `floor_delay_min` | — | — | `0.25` | Self-imposed delay before every request — lower bound (seconds). |
| `floor_delay_max` | — | — | `0.6` | Self-imposed delay before every request — upper bound (seconds). |
| `launch_timeout` | `DEXPORT_LAUNCH_TIMEOUT` | — | `90` | Seconds to wait for Discord's debug port after launching it. Raise it if a cold start is slower (`dexport configure --launch-timeout 180`). |
| — | `DEXPORT_HOME` | — | `~/.dexport` | Where config and cache are stored. |

`dexport configure --show` prints the stored file with defaults filled in;
environment overrides are deliberately not applied, so they can never be
written back. The delay floors have no flag or env var — edit `config.json`.
`launch_timeout` has no flag either, but `dexport configure --launch-timeout N`
writes it.
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
| `agents.py` | The coding-agent instructions: one prompt, rendered per agent tool. |
| `util.py` | Pure helpers: diacritics stripping, `normalize`, `is_snowflake`, `human_bytes`. |

Outside `src/` there is one more piece: `npm/` holds the wrapper that makes
`npm install -g dexport` work. `bootstrap.js` builds the private virtualenv,
`postinstall.js` runs it at install time, and `cli.js` is the `dexport`
command on your `PATH`. No program logic lives there.

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
