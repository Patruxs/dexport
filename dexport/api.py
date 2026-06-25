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


def _backoff(attempt: int) -> float:
    """Seconds to wait before retry ``attempt`` (1-based): 2, 4, 8, then capped at 10."""
    return float(min(2**attempt, MAX_BACKOFF))


def build_url(path: str) -> str:
    """Absolute URL for ``path`` (absolute URLs are passed through untouched)."""
    if path.startswith(("http://", "https://")):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return DISCORD_API_BASE + path


@dataclass(frozen=True)
class ApiRequest:
    """One Discord API call, described but not yet sent.

    ``body`` is JSON-serialised when it is not ``None``/``str``. Because the
    same object is used for ``--dry-run`` previews and for the real call, what
    you see is exactly what gets sent.
    """

    method: str
    path: str
    body: Any = None

    @property
    def url(self) -> str:
        return build_url(self.path)

    def body_text(self) -> str | None:
        """The body exactly as it will go over the wire (``None`` if no body)."""
        if self.body is None:
            return None
        if isinstance(self.body, str):
            return self.body
        return json.dumps(self.body, ensure_ascii=False)


@dataclass
class ApiResponse:
    status: int
    headers: dict[str, str]
    body: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        """Parsed body, or ``None`` for an empty body (e.g. 204 No Content)."""
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except json.JSONDecodeError as exc:
            raise ApiError(self.status, self.body, f"invalid JSON in response: {exc}") from exc


class ApiCore:
    """Issues Discord API requests through the renderer with rate limiting."""

    def __init__(
        self,
        session: Evaluator,
        headers: dict[str, str],
        limiter: RateLimiter | None = None,
        *,
        header_refresh: Callable[[], dict[str, str]] | None = None,
        max_retries: int = 5,
    ) -> None:
        self.session = session
        self.headers = dict(headers)
        self.limiter = limiter or RateLimiter()
        self._header_refresh = header_refresh
        self.max_retries = max_retries
        self._reauthed = False

    # -- low level ----------------------------------------------------------
    def _request_headers(self, has_body: bool) -> dict[str, str]:
        h = dict(self.headers)
        if has_body:
            h["content-type"] = "application/json"
        return h

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        raise_for_status: bool = True,
    ) -> ApiResponse:
        """Issue one request; see :meth:`execute`."""
        return self.execute(ApiRequest(method, path, body), raise_for_status=raise_for_status)

    def execute(self, req: ApiRequest, *, raise_for_status: bool = True) -> ApiResponse:
        """Send ``req``, transparently handling rate limits and retries.

        With ``raise_for_status`` (the default) any final non-2xx response is
        raised as :class:`ApiError`; pass ``False`` to inspect it yourself.
        """
        method = req.method.upper()
        url = req.url
        key = route_key(method, req.path)
        body_str = req.body_text()

        # Separate budgets per failure class so an early 401/500/network blip
        # does not silently eat the rate-limit retry allowance.
        net_tries = server_tries = rl_tries = 0
        refresh_error: Exception | None = None
        while True:
            self.limiter.acquire(key)
            payload = {
                "url": url,
                "method": method,
                "headers": self._request_headers(body_str is not None),
                "body": body_str,
            }
            raw = _check_fetch_result(self.session.evaluate(_FETCH_JS, payload))

            if raw["error"] or raw["status"] == 0:
                # Network-level failure inside the page.
                net_tries += 1
                if net_tries <= self.max_retries:
                    self.limiter.sleeper(_backoff(net_tries))
                    continue
                raise ApiError(0, None, f"fetch failed in renderer: {raw['error']}")

            resp = ApiResponse(
                status=int(raw["status"]),
                headers={k.lower(): v for k, v in (raw.get("headers") or {}).items()},
                body=raw.get("body") or "",
            )

            self.limiter.update(key, resp.headers)

            if resp.status == 429:
                rl_tries += 1
                retry_after = self.limiter.note_429(resp.headers, _safe_json(resp.body), key)
                if rl_tries <= self.max_retries:
                    # Only sleep when we are actually going to retry.
                    self.limiter.sleeper(retry_after + 0.1)
                    continue
                raise RateLimitError(
                    f"Still rate limited after {self.max_retries} retries on {key}."
                )

            if resp.status == 401 and self._header_refresh and not self._reauthed:
                # Token/context may have rotated; re-snapshot once and retry.
                self._reauthed = True
                try:
                    self.headers = dict(self._header_refresh())
                except Exception as exc:  # noqa: BLE001 - reported with the 401 below
                    refresh_error = exc
                else:
                    continue

            if resp.status >= 500:
                server_tries += 1
                if server_tries <= self.max_retries:
                    self.limiter.sleeper(_backoff(server_tries))
                    continue

            if resp.ok:
                # A fresh success means a later rotation can re-auth again.
                self._reauthed = False

            if raise_for_status and not resp.ok:
                raise _api_error(resp, refresh_error)

            return resp

    # -- convenience --------------------------------------------------------
    def get_json(self, path: str) -> Any:
        return self.request("GET", path).json()

    def post_json(self, path: str, body: Any) -> Any:
        return self.request("POST", path, body).json()

    def me(self) -> dict[str, Any]:
        me: dict[str, Any] = self.get_json("/users/@me")
        return me


def _api_error(resp: ApiResponse, refresh_error: Exception | None = None) -> ApiError:
    body = _safe_json(resp.body)
    if refresh_error is None:
        return ApiError(resp.status, body)
    # Don't hide *why* the automatic re-auth didn't help.
    detail = extract_message(body) or "unauthorized"
    err = ApiError(
        resp.status, body, f"{detail} (re-capturing headers also failed: {refresh_error})"
    )
    err.__cause__ = refresh_error
    return err


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return text
