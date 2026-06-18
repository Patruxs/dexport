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
