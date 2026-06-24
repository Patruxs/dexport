"""Tests for :mod:`dexport.api` — the in-page fetch core and its retry logic.

``FakeSession`` returns queued raw fetch results; the limiter is injected with
a fake clock/sleeper so nothing here ever waits.
"""

import dataclasses
import json

import pytest
from conftest import FakeSession
from conftest import resp as _resp

from dexport.api import ApiCore, ApiRequest, ApiResponse, build_url
from dexport.errors import ApiError, HeaderCaptureError, RateLimitError, SessionError
from dexport.ratelimit import RateLimiter


def _no_sleep_limiter():
    return RateLimiter(
        floor_min=0.0,
        floor_max=0.0,
        clock=lambda: 0.0,
        sleeper=lambda s: None,
        jitter=lambda a, b: 0.0,
    )


class _VirtualClock:
    """Clock that only advances when the limiter sleeps; records every sleep."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _recording_limiter() -> tuple[RateLimiter, _VirtualClock]:
    clock = _VirtualClock()
    limiter = RateLimiter(
        floor_min=0.0,
        floor_max=0.0,
        clock=lambda: clock.now,
        sleeper=clock.sleep,
        jitter=lambda a, b: 0.0,
    )
    return limiter, clock


# --------------------------------------------------------------------------
# Happy path / request shape
# --------------------------------------------------------------------------


def test_get_json_success():
    session = FakeSession([_resp(200, json.dumps({"username": "me", "id": "42"}))])
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    me = api.me()
    assert me["username"] == "me"
    # Verify the request carried our snapshotted headers and correct method.
    sent = session.calls[0]
    assert sent["method"] == "GET"
    assert sent["headers"]["authorization"] == "tok"
    assert sent["url"].endswith("/users/@me")


def test_body_serialization_for_post():
    session = FakeSession([_resp(200, json.dumps({"id": "9"}))])
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    api.post_json("/channels/1/messages", {"content": "hi"})
    sent = session.calls[0]
    assert sent["method"] == "POST"
    assert json.loads(sent["body"]) == {"content": "hi"}
    assert sent["headers"]["content-type"] == "application/json"


def test_get_without_body_has_no_content_type():
    session = FakeSession([_resp(200, "{}")])
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    api.get_json("/users/@me")
    sent = session.calls[0]
    assert sent["body"] is None
    assert "content-type" not in sent["headers"]
