"""Header snapshot — the trick that makes requests look like the client.

We watch the Discord page's outgoing requests and wait for the first
``/api/v9/*`` request that carries an ``Authorization`` header. We snapshot the
*whole* header cluster (not just the token) so that ``X-Super-Properties``,
``X-Discord-Locale``, ``X-Debug-Options`` etc. match the client build exactly.

The captured headers are sanitised: request headers that ``fetch`` is not
allowed to set (Cookie, Host, Origin, Sec-*, User-Agent, ...) are dropped,
because the browser attaches the correct values automatically for a same-origin
request. The result is kept in RAM only — never written to disk.
"""

from __future__ import annotations

from typing import Protocol

from .errors import HeaderCaptureError
from .session import RequestPredicate

# Headers the Fetch spec forbids scripts from setting; the browser supplies the
# right values itself for a same-origin request, so we strip them from the
# snapshot. content-type is stripped here and re-added per request body.
_FORBIDDEN_PREFIXES = ("sec-", "proxy-")
_FORBIDDEN_EXACT = {
    "accept-charset",
    "accept-encoding",
    "access-control-request-headers",
    "access-control-request-method",
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "cookie2",
    "date",
    "dnt",
    "expect",
    "host",
    "keep-alive",
    "origin",
    "referer",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "user-agent",
    "via",
}


class RequestWatcher(Protocol):
    """What :func:`capture_headers` needs from a session."""

    def wait_for_request(
        self,
        predicate: RequestPredicate,
        *,
        timeout: float,
        reload: bool = False,
        reload_timeout: float = 30.0,
    ) -> dict[str, str] | None: ...


def sanitize_headers(raw: dict[str, str]) -> dict[str, str]:
    """Drop forbidden/auto headers, lower-casing names for consistency."""
    out: dict[str, str] = {}
    for key, value in raw.items():
        lk = key.lower()
        # HTTP/2 pseudo-headers (:authority, :method, :path, :scheme) are not
        # valid fetch header names and make fetch throw "Invalid name".
        if lk.startswith(":"):
            continue
        if lk in _FORBIDDEN_EXACT or lk.startswith(_FORBIDDEN_PREFIXES):
            continue
        out[lk] = value
    return out


def looks_like_api_request(url: str, headers: dict[str, str]) -> bool:
    """True for an ``/api/v*`` request that carries an Authorization header."""
    if "/api/v" not in url:
        return False
    # Header keys from Playwright are already lower-cased.
    return bool(headers.get("authorization"))


def capture_headers(
    session: RequestWatcher,
    *,
    passive_timeout: float = 6.0,
    reload_timeout: float = 30.0,
) -> dict[str, str]:
    """Snapshot the client's authorized request headers.

    First we listen passively for a few seconds (Discord makes background API
    calls constantly). If nothing shows up, we reload the page to force a burst
    of authorized requests and listen again.
    """
    raw = session.wait_for_request(looks_like_api_request, timeout=passive_timeout)
    if raw is None:
        # The listener's countdown starts before the (blocking) reload, so give
        # it a budget larger than the reload's own timeout — otherwise a
        # slow-to-commit reload would consume the entire window and the request
        # that fires just after commit would be missed.
        raw = session.wait_for_request(
            looks_like_api_request,
            timeout=reload_timeout + passive_timeout,
            reload=True,
            reload_timeout=reload_timeout,
        )
    if raw is None:
        raise HeaderCaptureError(
            "Never observed an authorized /api request from Discord. Make sure "
            "you are logged in and a channel is open, then try again."
        )

    headers = sanitize_headers(raw)
    if not headers.get("authorization"):
        raise HeaderCaptureError("Captured a request but it had no Authorization header.")
    return headers
