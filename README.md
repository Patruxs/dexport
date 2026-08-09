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
