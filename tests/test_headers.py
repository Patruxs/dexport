from __future__ import annotations

from typing import Any

import pytest

from dexport.errors import HeaderCaptureError
from dexport.headers import capture_headers, looks_like_api_request, sanitize_headers

# --------------------------------------------------------------------------
# sanitize_headers
# --------------------------------------------------------------------------


def test_sanitize_keeps_client_fingerprint_headers():
    raw = {
        "Authorization": "tok",
        "X-Super-Properties": "abc",
        "X-Discord-Locale": "en-US",
        "X-Debug-Options": "bugReporterEnabled",
        "Accept": "*/*",
        "Accept-Language": "en-US",
    }
    out = sanitize_headers(raw)
    assert out["authorization"] == "tok"
    assert out["x-super-properties"] == "abc"
    assert out["x-discord-locale"] == "en-US"
    assert out["x-debug-options"] == "bugReporterEnabled"


def test_sanitize_drops_http2_pseudo_headers():
    # Discord speaks HTTP/2, so all_headers() includes :authority/:method/etc.
    # These must be dropped or fetch throws "Invalid name".
    raw = {
        ":authority": "discord.com",
        ":method": "GET",
        ":path": "/api/v9/users/@me",
        ":scheme": "https",
        "Authorization": "tok",
        "X-Super-Properties": "abc",
    }
    out = sanitize_headers(raw)
    assert all(not k.startswith(":") for k in out)
    assert out == {"authorization": "tok", "x-super-properties": "abc"}


def test_sanitize_drops_forbidden_headers():
    raw = {
        "Authorization": "tok",
        "Cookie": "secret",
        "Host": "discord.com",
        "Origin": "https://discord.com",
        "Referer": "https://discord.com/channels/@me",
        "User-Agent": "Discord/1.0",
        "Sec-Fetch-Site": "same-origin",
        "Content-Length": "42",
        "Accept-Encoding": "gzip",
    }
    out = sanitize_headers(raw)
    assert "cookie" not in out
    assert "host" not in out
    assert "origin" not in out
    assert "referer" not in out
    assert "user-agent" not in out
    assert "sec-fetch-site" not in out
    assert "content-length" not in out
    assert "accept-encoding" not in out
    assert out == {"authorization": "tok"}


# --------------------------------------------------------------------------
# looks_like_api_request
# --------------------------------------------------------------------------

API_URL = "https://discord.com/api/v9/users/@me"


@pytest.mark.parametrize(
    ("url", "headers", "expected"),
    [
        (API_URL, {"authorization": "tok"}, True),
        ("https://discord.com/api/v10/channels/1/messages", {"authorization": "tok"}, True),
        ("https://discord.com/assets/app.js", {"authorization": "tok"}, False),
        ("https://discord.com/channels/1/2", {"authorization": "tok"}, False),
        (API_URL, {}, False),
        (API_URL, {"authorization": ""}, False),
        (API_URL, {"x-super-properties": "abc"}, False),
    ],
)
def test_looks_like_api_request(url, headers, expected):
    assert looks_like_api_request(url, headers) is expected


# --------------------------------------------------------------------------
# capture_headers
# --------------------------------------------------------------------------

RAW_AUTHORIZED = {
    "Authorization": "tok",
    "X-Super-Properties": "abc",
    "Cookie": "secret",
    "User-Agent": "Discord/1.0",
    ":authority": "discord.com",
}


class FakeWatcher:
    """Records each ``wait_for_request`` call and returns queued results in order."""

    def __init__(self, results: list[dict[str, str] | None]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def wait_for_request(self, predicate, *, timeout, reload=False, reload_timeout=30.0):
        self.calls.append(
            {
                "predicate": predicate,
                "timeout": timeout,
                "reload": reload,
                "reload_timeout": reload_timeout,
            }
        )
        if not self._results:
            raise AssertionError("capture_headers waited more times than expected")
        return self._results.pop(0)


def test_capture_passive_hit_returns_sanitised_headers_without_reload():
    watcher = FakeWatcher([RAW_AUTHORIZED])
    out = capture_headers(watcher, passive_timeout=1.5, reload_timeout=4.0)
    assert out == {"authorization": "tok", "x-super-properties": "abc"}
    assert len(watcher.calls) == 1
    assert watcher.calls[0]["reload"] is False
    assert watcher.calls[0]["timeout"] == 1.5


def test_capture_waits_for_an_authorized_api_request():
    watcher = FakeWatcher([RAW_AUTHORIZED])
    capture_headers(watcher, passive_timeout=1.0)
    predicate = watcher.calls[0]["predicate"]
    assert predicate(API_URL, {"authorization": "tok"}) is True
    assert predicate("https://discord.com/assets/app.js", {"authorization": "tok"}) is False
    assert predicate(API_URL, {}) is False


def test_capture_passive_miss_then_reload_hit():
    watcher = FakeWatcher([None, RAW_AUTHORIZED])
    out = capture_headers(watcher, passive_timeout=1.5, reload_timeout=4.0)
    assert out["authorization"] == "tok"
    assert len(watcher.calls) == 2
    second = watcher.calls[1]
    assert second["reload"] is True
    assert second["reload_timeout"] == 4.0
    # Listener budget must exceed the reload's own timeout (see headers.py).
    assert second["timeout"] == 4.0 + 1.5
    assert second["predicate"] is watcher.calls[0]["predicate"]


def test_capture_both_misses_raises_with_login_hint():
    watcher = FakeWatcher([None, None])
    with pytest.raises(HeaderCaptureError, match="logged in"):
        capture_headers(watcher, passive_timeout=0, reload_timeout=0)
    assert len(watcher.calls) == 2


@pytest.mark.parametrize(
    "raw",
    [
        {"Cookie": "secret", "X-Super-Properties": "abc"},
        {"Authorization": "", "X-Super-Properties": "abc"},
    ],
)
def test_capture_request_without_authorization_raises(raw):
    watcher = FakeWatcher([raw])
    with pytest.raises(HeaderCaptureError, match="no Authorization"):
        capture_headers(watcher, passive_timeout=0)
    assert len(watcher.calls) == 1


def test_capture_uses_default_timeouts_when_not_given():
    watcher = FakeWatcher([None, RAW_AUTHORIZED])
    capture_headers(watcher)
    passive, reload = watcher.calls
    assert passive["timeout"] > 0
    assert reload["reload_timeout"] > passive["timeout"]
    assert reload["timeout"] == reload["reload_timeout"] + passive["timeout"]
