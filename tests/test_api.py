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


def test_content_type_added_for_string_body():
    session = FakeSession([_resp(200, "{}")])
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    api.request("POST", "/x", "raw")
    sent = session.calls[0]
    assert sent["body"] == "raw"
    assert sent["headers"]["content-type"] == "application/json"


def test_content_type_does_not_leak_into_snapshot_headers():
    session = FakeSession([_resp(200, "{}"), _resp(200, "{}")])
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    api.post_json("/x", {"a": 1})
    api.get_json("/y")
    assert "content-type" not in session.calls[1]["headers"]
    assert "content-type" not in api.headers


def test_method_is_uppercased():
    session = FakeSession([_resp(200, "{}")])
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    api.request("delete", "/x")
    assert session.calls[0]["method"] == "DELETE"


def test_execute_sends_prebuilt_request_url():
    session = FakeSession([_resp(204, "")])
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    r = api.execute(ApiRequest("DELETE", "/channels/1/messages/2"))
    assert r.status == 204
    assert r.json() is None
    assert session.calls[0]["url"] == "https://discord.com/api/v9/channels/1/messages/2"


def test_response_headers_are_lowercased():
    session = FakeSession(
        [_resp(200, "{}", {"X-RateLimit-Remaining": "3", "Content-Type": "application/json"})]
    )
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    r = api.request("GET", "/x")
    assert r.headers == {"x-ratelimit-remaining": "3", "content-type": "application/json"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "https://cdn.discordapp.com/attachments/1/2/a.png",
            "https://cdn.discordapp.com/attachments/1/2/a.png",
        ),
        ("http://localhost:9222/json", "http://localhost:9222/json"),
        ("users/@me", "https://discord.com/api/v9/users/@me"),
        ("/users/@me", "https://discord.com/api/v9/users/@me"),
        ("/channels/1/messages?limit=5", "https://discord.com/api/v9/channels/1/messages?limit=5"),
    ],
)
def test_build_url(path, expected):
    assert build_url(path) == expected


# --------------------------------------------------------------------------
# Malformed renderer replies
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        {"status": 200},  # missing headers/body/error
        {"status": 200, "headers": {}, "body": "{}"},  # missing error
        "not a dict",
        None,
    ],
)
def test_malformed_fetch_result_raises_session_error_without_retry(raw):
    session = FakeSession([raw] * 5)
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    with pytest.raises(SessionError, match="malformed fetch result"):
        api.get_json("/users/@me")
    assert len(session.calls) == 1


# --------------------------------------------------------------------------
# 429 rate limits
# --------------------------------------------------------------------------


def test_429_then_success_retries():
    session = FakeSession(
        [
            _resp(
                429,
                json.dumps({"retry_after": 0.01, "global": False}),
                {"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "0.01"},
            ),
            _resp(200, json.dumps({"ok": True})),
        ]
    )
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    assert api.get_json("/users/@me") == {"ok": True}
    assert len(session.calls) == 2


def test_429_past_retry_budget_raises_rate_limit_error():
    rl = _resp(
        429,
        json.dumps({"retry_after": 0}),
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "0"},
    )
    session = FakeSession([rl] * 10)
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter(), max_retries=2)
    with pytest.raises(RateLimitError, match="GET /users/@me"):
        api.get_json("/users/@me")
    assert len(session.calls) == 3  # initial + max_retries


def test_429_sleeps_for_retry_after_plus_margin():
    limiter, clock = _recording_limiter()
    session = FakeSession(
        [_resp(429, json.dumps({"retry_after": 1.5, "global": False})), _resp(200, "{}")]
    )
    api = ApiCore(session, {"authorization": "tok"}, limiter)
    api.get_json("/channels/123456789012345678/messages")
    assert clock.sleeps == [pytest.approx(1.6)]


def test_exhausted_route_budget_delays_next_call_on_same_route():
    limiter, clock = _recording_limiter()
    session = FakeSession(
        [
            _resp(200, "{}", {"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "2.5"}),
            _resp(200, "{}"),
        ]
    )
    api = ApiCore(session, {"authorization": "tok"}, limiter)
    api.get_json("/channels/1/messages")
    api.get_json("/channels/1/messages")
    assert clock.sleeps == [2.5]


def test_retry_budgets_are_independent():
    # A 500 must not consume the 429 retry budget (max_retries=2).
    rl_429 = _resp(
        429,
        json.dumps({"retry_after": 0}),
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "0"},
    )
    session = FakeSession([_resp(500, "boom"), rl_429, rl_429, _resp(200, json.dumps({"ok": 1}))])
    api = ApiCore(session, {"authorization": "t"}, _no_sleep_limiter(), max_retries=2)
    assert api.get_json("/users/@me") == {"ok": 1}
    assert len(session.calls) == 4


# --------------------------------------------------------------------------
# 401 re-auth
# --------------------------------------------------------------------------


def test_401_triggers_single_reauth():
    session = FakeSession(
        [
            _resp(401, json.dumps({"message": "401: Unauthorized"})),
            _resp(200, json.dumps({"ok": True})),
        ]
    )
    refreshed = {"n": 0}

    def refresh():
        refreshed["n"] += 1
        return {"authorization": "new-token"}

    api = ApiCore(session, {"authorization": "old"}, _no_sleep_limiter(), header_refresh=refresh)
    assert api.get_json("/users/@me") == {"ok": True}
    assert refreshed["n"] == 1
    assert session.calls[1]["headers"]["authorization"] == "new-token"


def test_reauth_resets_after_success():
    # Two separate token rotations in one session must both recover.
    session = FakeSession(
        [
            _resp(401, json.dumps({"message": "401"})),
            _resp(200, json.dumps({"ok": 1})),
            _resp(401, json.dumps({"message": "401"})),
            _resp(200, json.dumps({"ok": 2})),
        ]
    )
    n = {"c": 0}

    def refresh():
        n["c"] += 1
        return {"authorization": f"tok{n['c']}"}

    api = ApiCore(session, {"authorization": "tok0"}, _no_sleep_limiter(), header_refresh=refresh)
    assert api.get_json("/users/@me") == {"ok": 1}
    assert api.get_json("/users/@me") == {"ok": 2}
    assert n["c"] == 2  # reauth fired on both 401s, not just the first
