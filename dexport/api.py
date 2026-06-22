"""API core — the heart. In-page ``fetch`` + rate limiting.

Every Discord call is executed by ``page.evaluate`` inside the Discord renderer
so it is same-origin (no CORS, cookies + real User-Agent attached) and carries
the snapshotted client headers. The Python side handles rate limiting, retries,
and turning non-2xx responses into :class:`ApiError`.

Two ways to make a call:

* :meth:`ApiCore.request` — ad-hoc ``(method, path, body)``.
* :meth:`ApiCore.execute` — run a pre-built :class:`ApiRequest`. Builders in
  :mod:`dexport.messages` return these, so the CLI can *preview* exactly the
  request that will be sent (``--dry-run``) and then send that same object.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from .errors import ApiError, RateLimitError, SessionError, extract_message
from .ratelimit import RateLimiter, route_key
from .session import Evaluator

DISCORD_API_BASE = "https://discord.com/api/v9"

# Runs in the Discord renderer. Receives one arg {url, method, headers, body}.
_FETCH_JS = """
async (req) => {
  const opts = { method: req.method, headers: req.headers };
  if (req.body !== null && req.body !== undefined) { opts.body = req.body; }
  let r;
  try {
    r = await fetch(req.url, opts);
  } catch (e) {
    return { status: 0, headers: {}, body: '', error: String(e) };
  }
  const text = await r.text();
  const h = {};
  r.headers.forEach((v, k) => { h[k] = v; });
  return { status: r.status, headers: h, body: text, error: null };
}
"""

#: Cap (seconds) on the exponential backoff between retries of one request.
MAX_BACKOFF = 10.0


class FetchResult(TypedDict):
    """What ``_FETCH_JS`` resolves to. Keep in sync with the JS above."""

    status: int
    headers: dict[str, str]
    body: str
    error: str | None


_FETCH_RESULT_KEYS = frozenset(FetchResult.__required_keys__)


def _check_fetch_result(raw: object) -> FetchResult:
    """Fail fast if the renderer's reply doesn't match :class:`FetchResult`.

    A broken JS<->Python contract must not look like a flaky network (which
    would be retried with backoff for ~30 s before surfacing).
    """
    if not isinstance(raw, dict) or not raw.keys() >= _FETCH_RESULT_KEYS:
        raise SessionError(f"Renderer returned a malformed fetch result: {raw!r:.200}")
    return raw  # type: ignore[return-value]
