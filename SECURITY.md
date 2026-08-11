# Security Policy

## Supported versions

dexport is a single-developer tool with a linear history: only the latest
release on `main` is supported. Fixes go into a new release rather than a
backport.

| Version | Supported |
| --- | --- |
| 0.1.x | ✅ |
| < 0.1 | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting instead:
[**Report a vulnerability**](https://github.com/Patruxs/dexport/security/advisories/new)
(Security → Advisories → Report a vulnerability). That opens a private thread
visible only to the maintainer.

Please include:

- what you can do with the bug (read a token, run code, escalate a write),
- the version (`dexport --version`), OS and Python version,
- the smallest reproduction you have.

Expect an acknowledgement within **7 days** and a fix or a plan within **30**.
If you do not hear back in that window, feel free to open a public issue
saying only that a private report is unanswered — no details.

Please do not test against accounts, servers, or data that are not yours.

## What dexport does with your credentials

This is the part worth scrutinising, so it is spelled out explicitly.

- **Nothing is ever written to disk.** dexport snapshots the Discord client's
  request headers — including `Authorization` — and keeps them **in RAM only**,
  on `ApiCore.headers`, for the lifetime of a single command. They are gone
  when the process exits.
- **Nothing is logged or printed.** Headers are never echoed, never included in
  an error message, and never part of `--dry-run` output. If you ever see an
  authorization value in dexport's output, that is a vulnerability — report it.
- **`~/.dexport/` holds no secrets.** Only `config.json` (port, binary path,
  delay window), `cache.json` (guild/channel name ↔ ID mappings) and
  `notice-shown` (a marker for the one-time Terms-of-Service notice).
- **No password, no bot token, no OAuth flow.** dexport never asks for
  credentials; it reuses the session your desktop client already has.
- **Nothing is sent anywhere except Discord.** The only network destination is
  `discord.com/api/v9`, via a `fetch` that runs inside Discord's own renderer.
  dexport has no telemetry and no update check.

### Things that are working as intended, not vulnerabilities

- **The CDP port is unauthenticated.** `--remote-debugging-port` exposes full
  control of the Discord renderer to anything that can reach it. dexport binds
  nothing itself; it connects to `127.0.0.1`. Do not forward that port, and do
  not run it on a machine you share with untrusted users.
- **Any local process can read the same headers.** That is a property of CDP,
  not of dexport.
- **dexport automates a user account,** which violates Discord's Terms of
  Service and risks permanent account termination. That is a documented,
  deliberate trade-off (see the README), not a bug.
