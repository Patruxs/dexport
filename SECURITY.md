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
