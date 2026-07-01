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


def test_401_after_refresh_is_not_refreshed_twice():
    session = FakeSession([_resp(401, json.dumps({"message": "401"}))] * 5)
    calls = {"n": 0}

    def refresh():
        calls["n"] += 1
        return {"authorization": "new"}

    api = ApiCore(session, {"authorization": "old"}, _no_sleep_limiter(), header_refresh=refresh)
    with pytest.raises(ApiError) as exc:
        api.get_json("/users/@me")
    assert exc.value.status == 401
    assert calls["n"] == 1
    assert len(session.calls) == 2
    assert session.calls[1]["headers"]["authorization"] == "new"


def test_401_without_refresh_returns_response_after_one_call():
    session = FakeSession([_resp(401, json.dumps({"message": "401: Unauthorized"}))] * 3)
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    r = api.request("GET", "/users/@me", raise_for_status=False)
    assert r.status == 401
    assert len(session.calls) == 1


def test_401_without_refresh_raises_plain_api_error():
    session = FakeSession([_resp(401, json.dumps({"message": "401: Unauthorized"}))] * 3)
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    with pytest.raises(ApiError) as exc:
        api.get_json("/users/@me")
    assert exc.value.status == 401
    assert "re-capturing" not in str(exc.value)
    assert len(session.calls) == 1


def test_401_with_failing_refresh_reports_both_failures():
    session = FakeSession([_resp(401, json.dumps({"message": "401: Unauthorized"}))] * 3)
    cause = HeaderCaptureError("no api request seen")

    def refresh():
        raise cause

    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter(), header_refresh=refresh)
    with pytest.raises(ApiError) as exc:
        api.get_json("/users/@me")
    err = exc.value
    assert err.status == 401
    assert "401: Unauthorized" in str(err)
    assert "re-capturing headers also failed: no api request seen" in str(err)
    assert err.__cause__ is cause
    assert len(session.calls) == 1  # no retry when the refresh itself failed
    assert api.headers == {"authorization": "tok"}  # old headers kept


# --------------------------------------------------------------------------
# 4xx client errors
# --------------------------------------------------------------------------


def test_403_raises_api_error_with_discord_message():
    session = FakeSession(
        [_resp(403, json.dumps({"message": "Missing Access", "code": 50001}))] * 3
    )
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    with pytest.raises(ApiError) as exc:
        api.get_json("/channels/1/messages")
    err = exc.value
    assert err.status == 403
    assert err.body["message"] == "Missing Access"
    assert "Missing Access" in str(err)
    assert "403" in str(err)
    assert len(session.calls) == 1  # client errors are not retried


def test_4xx_with_raise_for_status_false_returns_response():
    session = FakeSession([_resp(404, json.dumps({"message": "Unknown Channel"}))])
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter())
    r = api.request("GET", "/channels/0", raise_for_status=False)
    assert r.status == 404
    assert not r.ok
    assert r.json() == {"message": "Unknown Channel"}


# --------------------------------------------------------------------------
# 5xx / network backoff
# --------------------------------------------------------------------------


def test_500_retries_then_raises():
    session = FakeSession([_resp(500, "boom")] * 10)
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter(), max_retries=2)
    with pytest.raises(ApiError) as exc:
        api.get_json("/users/@me")
    assert exc.value.status == 500


def test_5xx_backoff_sleeps_double_then_succeeds():
    limiter, clock = _recording_limiter()
    session = FakeSession(
        [_resp(500, "boom"), _resp(502, "bad gateway"), _resp(200, json.dumps({"ok": 1}))]
    )
    api = ApiCore(session, {"authorization": "tok"}, limiter)
    assert api.get_json("/users/@me") == {"ok": 1}
    assert clock.sleeps == [2.0, 4.0]
    assert len(session.calls) == 3


def test_5xx_backoff_is_capped():
    limiter, clock = _recording_limiter()
    session = FakeSession([_resp(503, "")] * 10)
    api = ApiCore(session, {"authorization": "tok"}, limiter, max_retries=5)
    with pytest.raises(ApiError) as exc:
        api.get_json("/users/@me")
    assert exc.value.status == 503
    assert clock.sleeps == [2.0, 4.0, 8.0, 10.0, 10.0]
    assert len(session.calls) == 6


def test_network_error_in_renderer_retries_then_raises():
    session = FakeSession([_resp(0, "", {}, error="TypeError: failed to fetch")] * 10)
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter(), max_retries=1)
    with pytest.raises(ApiError):
        api.get_json("/users/@me")


def test_network_error_details_surface_in_api_error():
    session = FakeSession([_resp(0, "", {}, error="TypeError: failed to fetch")] * 10)
    api = ApiCore(session, {"authorization": "tok"}, _no_sleep_limiter(), max_retries=1)
    with pytest.raises(ApiError, match="TypeError: failed to fetch") as exc:
        api.get_json("/users/@me")
    assert exc.value.status == 0
    assert len(session.calls) == 2


def test_network_error_backoff_matches_5xx():
    limiter, clock = _recording_limiter()
    session = FakeSession(
        [_resp(0, "", {}, error="TypeError: Failed to fetch")] * 2 + [_resp(200, "{}")]
    )
    api = ApiCore(session, {"authorization": "tok"}, limiter)
    api.get_json("/x")
    assert clock.sleeps == [2.0, 4.0]


# --------------------------------------------------------------------------
# ApiRequest
# --------------------------------------------------------------------------


def test_api_request_url_is_absolute():
    assert ApiRequest("GET", "/users/@me").url == "https://discord.com/api/v9/users/@me"
