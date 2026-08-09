# Architecture

How dexport is put together, what each stage guarantees, and where to make the
common changes. This document stands on its own: the design notes the pipeline
was derived from are not part of the repository.

## The pipeline

```
launcher/  ──►  session.py  ──►  headers.py  ──►  api.py + ratelimit.py  ──►  resolver.py  ──►  cli/
(CDP port       (attach over     (snapshot the     (in-page fetch, per-route     (name → ID,      (read/export/
 alive? else     CDP, pick the    first authorized  limiter, retries)             cached, fuzzy)   send/reply/...)
 launch Discord) app page)        /api/v9 request)
```

`Dexport.acquire()` in `client.py` runs the first five stages in order and
returns a `Dexport` holding a live `Session`, an `ApiCore` and a `Resolver`.
Every command runs inside `with connect(ctx) as dx:` (`cli/common.py`), which
releases the CDP attachment and persists the resolver cache on exit — also
when the command fails. If a later stage raises during `acquire()`, the
session opened by an earlier one is closed before the error propagates.

| Stage | Module | What it guarantees on success | Raises |
| --- | --- | --- | --- |
| Launcher | `launcher/` | `http://127.0.0.1:<port>/json/version` answers 200, i.e. a Discord process is listening for CDP on `port`. If it is not, `discovery.py` finds the binary for this OS and `process.py` starts it detached with `--remote-debugging-port=<port>`; the port is then polled every 0.75 s for up to 40 s. With `--restart` the running client is first sent SIGTERM (SIGKILL after 5 s; `taskkill /F` on Windows) and dexport waits up to 10 s for the single-instance lock to release. | `LauncherError` |
| Session | `session.py` | A Playwright `Page` that is the real Discord app renderer: a `discord.com` / `discordapp.com` / `ptb.` / `canary.` URL, scored to prefer `/channels` and `/app` and to penalise overlay, splash, notification, devtools and `about:blank` pages. Only two primitives are exposed: `evaluate()` and `wait_for_request()`. | `SessionError` |
| Header snapshot | `headers.py` | A dict of lower-cased request headers that contains `authorization` and that `fetch` will accept. Held in memory only. | `HeaderCaptureError` |
| API core | `api.py`, `ratelimit.py` | Every call goes through `ApiCore.execute()`: floor delay → in-page `fetch` → limiter bookkeeping → retry or raise. A returned `ApiResponse` is 2xx unless the caller passed `raise_for_status=False`. | `ApiError`, `RateLimitError`, `SessionError` |
| Resolver | `resolver.py` | `-g`/`-c` names become IDs: exact ID match first, then a diacritics-insensitive fuzzy match that must score ≥ 60 %; an ID-shaped query that matches nothing is used verbatim. Guild and channel lists are cached in `cache.json`. | `ResolveError` |
| Commands | `cli/` | Verbs only compose the layers above. Any `DexportError` becomes `error: <message>` on stderr and exit code 1. | — |

All of these errors derive from `DexportError` (`errors.py`). Anything else
escaping a command is a genuine bug and surfaces as a traceback.

## The header snapshot

Discord's client sends a cluster of headers with every API call:
`Authorization`, `X-Super-Properties` (base64 client build info),
`X-Discord-Locale`, `X-Discord-Timezone`, `X-Debug-Options`, and so on.
Reconstructing them would mean tracking client builds. Instead
`capture_headers(session)` watches the page's outgoing requests and snapshots
the **whole header cluster** of the first one that matches
`looks_like_api_request` (URL contains `/api/v` and an `authorization` header
is present). That cluster is then splatted into every in-page `fetch`, so each
request carries a valid, current header set with zero maintenance on our side.
The point is correctness, not concealment: `X-Super-Properties` encodes the
client build, a stale or invented value is what gets requests rejected or a
session invalidated, and the only value guaranteed to be right is the one the
client itself just sent. `User-Agent` is not
needed at all: the fetch runs in Discord's renderer, so the browser attaches
the real one.

Two attempts are made: listen passively for 6 s (Discord makes background
calls constantly); if nothing shows up, reload the page (`wait_until="commit"`,
30 s) while listening with a 36 s budget, because a reload provokes a burst of
authorized requests. Both failing raises `HeaderCaptureError`.

`sanitize_headers` then drops what `fetch` refuses or overrides itself: HTTP/2
pseudo-headers (`:authority`, `:path`, ...), `sec-*` / `proxy-*`, and
forbidden names such as `cookie`, `host`, `origin`, `referer`, `user-agent`,
`content-length`, `accept-encoding`. `content-type` is stripped too and
re-added as `application/json` by `ApiCore` only when a request has a body.
The result lives on `ApiCore.headers` for the duration of one command and is
never written to disk.
