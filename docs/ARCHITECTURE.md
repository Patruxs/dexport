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

## The in-page fetch contract

`ApiCore.execute` runs `_FETCH_JS` (an `async (req) => {...}` arrow function)
via `Session.evaluate` with a single argument `{url, method, headers, body}`
where `body` is a string or `null`. The function always resolves — it never
rejects — to a `FetchResult`:

| Key | Type | Meaning |
| --- | --- | --- |
| `status` | int | HTTP status; `0` when `fetch` itself threw |
| `headers` | `{name: value}` | response headers (names lower-cased by the browser) |
| `body` | str | response text (may be empty, e.g. 204) |
| `error` | str or `null` | `String(e)` of a thrown `fetch`, else `null` |

Because the request is same-origin there is no CORS and every response header
is readable, including `X-RateLimit-*`. `_check_fetch_result` verifies that the
reply is a dict containing all four keys and raises `SessionError` immediately
otherwise: a broken JS↔Python contract must fail fast rather than look like a
flaky network, which would be retried with backoff for about half a minute.

## Rate limiting and retries

`RateLimiter` (`ratelimit.py`) keeps one entry per **route key**:
`route_key(method, path)` = `METHOD path` with the query string dropped and
every run of 15+ digits replaced by `{id}`, e.g. `GET /channels/{id}/messages`.
This approximates Discord's per-route + major-parameter buckets;
`X-RateLimit-Bucket` is deliberately not tracked.

- `acquire(key)` runs before every request: (1) if a global limit is active,
  sleep until it clears; (2) if the route's `remaining` is 0 and its reset is
  in the future, sleep until then; (3) sleep the **floor delay**, a uniform
  random value in `[floor_delay_min, floor_delay_max]` (0.25–0.6 s by default,
  configurable in `config.json`).
- `update(key, headers)` runs after every response and records
  `x-ratelimit-remaining` and `now + x-ratelimit-reset-after` for the route.
  Both headers must be present; unparsable values are ignored.
- `note_429(headers, body, key)` picks `retry_after` from the JSON body
  (seconds), else the `retry-after` header, else 1.0 s. If the
  `x-ratelimit-global` header is present or the body has `global: true`, every
  route is blocked until `now + retry_after`; otherwise only that route is.

`ApiCore.execute` (`api.py`) wraps this in a retry loop with three
**independent budgets** of `max_retries` (5) each, so an early network blip or
500 does not eat the rate-limit allowance:

| Outcome | Action |
| --- | --- |
| network failure (`error` set or `status == 0`) | sleep `min(2^n, 10)` s — 2, 4, 8, 10, 10 — and retry; then `ApiError(status=0)` |
| 429 | `note_429`, sleep `retry_after + 0.1` s, retry; after 5 → `RateLimitError` |
| 401 | at most **one** re-auth per failure streak: call `header_refresh` (re-runs `capture_headers`) and retry immediately, consuming no budget. If the refresh itself throws, the 401 is raised as `ApiError` with that failure appended to the message and set as `__cause__`. |
| 5xx | sleep `min(2^n, 10)` s and retry; after 5 → `ApiError` |
| 2xx | re-arms the 401 latch; returned |
| any other non-2xx | `ApiError(status, parsed body)` — or returned as-is with `raise_for_status=False` |

All sleeps go through `limiter.sleeper`, so tests inject a no-op. Write verbs
additionally call `human_pause()` (0.4–1.2 s) after confirmation and before
executing.

## The request-builder pattern

`ApiRequest(method, path, body)` (`api.py`) is a frozen dataclass describing a
call that has not been sent. `.url` prefixes `DISCORD_API_BASE`
(`https://discord.com/api/v9`; absolute URLs pass through) and `.body_text()`
is the exact wire body: `None`, a `str` as-is, or `json.dumps(body,
ensure_ascii=False)`.

The builders in `messages.py` (`send_message_request`, `edit_message_request`,
`delete_message_request`, `add_reaction_request`, `remove_reaction_request`,
`history_request`) return `ApiRequest`s and are the only code that knows the
message URL layout. `run_write` in `cli/common.py` calls `build(channel_id)`
once and either previews that object (`preview()` prints `METHOD url` and the
pretty-printed body) for `--dry-run` or hands it to `ApiCore.execute`. One
object, one source of truth — the preview and the real request cannot drift.
That is also why `reply --dry-run` shows `fail_if_not_exists: false`: it is
part of what is sent.

`run_write` in order: with `--dry-run --channel-id` it previews without
touching Discord at all (not even launching it); otherwise it connects,
resolves the target, builds the request, previews it if `--dry-run`, else
confirms (unless `--yes`), pauses, executes and prints `done(response, label)`.
`ApiCore.request(method, path, body)` is a convenience wrapper that builds the
`ApiRequest` inline; `get_json`/`post_json`/`me()` sit on top of it.

## Settings precedence

**CLI flag > environment variable > `config.json` > built-in default**, applied
in exactly these places:

1. Defaults are the `Settings` dataclass field defaults in `config.py`.
   `floor_delay_min`/`max` import theirs from `ratelimit.DEFAULT_FLOOR_MIN`/`MAX`
   so the limiter and the config file cannot disagree.
2. `Settings.load_file(paths)` reads `config.json` (`_read_json`: missing,
   corrupt or non-object → `{}`) through `Settings.from_dict`, which ignores
   unknown keys and falls back to the default for any value it cannot coerce.
3. `Settings.with_env_overrides(env)` applies `DEXPORT_PORT` (only if all
   digits) and `DEXPORT_DISCORD_BINARY`. `Settings.load()` is steps 2 + 3.
4. The root callback in `cli/app.py` stores `--port`, `--restart`, `--binary`
   in `ctx.obj` as a `ConnectionOptions`. `connect(ctx)` calls
   `ConnectionOptions.settings()`, which is
   `Settings.load(paths).with_overrides(port=..., discord_binary=...)`
   (`None` means "flag not given"), then
   `Dexport.acquire(settings=..., force_restart=opts.restart)`.

`DEXPORT_HOME` is not a setting: `Paths.default()` reads it at call time to
locate both files. `--restart` is a per-invocation action and is never
persisted. `configure` deliberately starts from `Settings.load_file()` (no env
overrides) so a transient `DEXPORT_PORT` can never be baked into the file;
consequently `configure --show` prints the stored values, not the env-merged
ones.
