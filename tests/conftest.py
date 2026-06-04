"""Shared fixtures. Nothing here needs a running Discord client.

* ``dexport_home`` (autouse) — points ``DEXPORT_HOME`` at a temp dir so no
  test can ever read or write the developer's real ``~/.dexport``.
* ``FakeSession`` / ``fake_session`` — a stand-in for the CDP session that
  returns queued fetch results (see :func:`resp`).
* ``no_sleep_limiter`` — a :class:`RateLimiter` that never sleeps.
* ``FakeApi`` — records every request and returns queued responses; use it
  where code takes an ``ApiCore``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dexport.api import ApiRequest, ApiResponse
from dexport.ratelimit import RateLimiter

# --------------------------------------------------------------------------
# Isolation
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def dexport_home(tmp_path, monkeypatch):
    """Every test gets its own ``$DEXPORT_HOME``; returns the directory."""
    home = tmp_path / "dexport-home"
    monkeypatch.setenv("DEXPORT_HOME", str(home))
    monkeypatch.delenv("DEXPORT_PORT", raising=False)
    monkeypatch.delenv("DEXPORT_DISCORD_BINARY", raising=False)
    return home


# --------------------------------------------------------------------------
# Session / fetch fakes (for ApiCore)
# --------------------------------------------------------------------------


def resp(status: int, body: str = "", headers: dict[str, str] | None = None, error=None) -> dict:
    """Build a raw fetch result exactly as ``_FETCH_JS`` would return it."""
    return {"status": status, "body": body, "headers": headers or {}, "error": error}


def json_resp(status: int, payload: Any, headers: dict[str, str] | None = None) -> dict:
    return resp(status, json.dumps(payload), headers)


class FakeSession:
    """Stands in for a CDP session; returns queued fetch results in order."""

    def __init__(self, responses=()):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def evaluate(self, expression, arg=None):
        self.calls.append(arg)
        if not self._responses:
            raise AssertionError("no more fake responses")
        return self._responses.pop(0)


@pytest.fixture
def fake_session():
    return FakeSession


@pytest.fixture
def no_sleep_limiter():
    return RateLimiter(
        floor_min=0.0,
        floor_max=0.0,
        clock=lambda: 0.0,
        sleeper=lambda s: None,
        jitter=lambda a, b: 0.0,
    )


# --------------------------------------------------------------------------
# API fake (for code that takes an ApiCore: messages, resolver, cli)
# --------------------------------------------------------------------------


class FakeApi:
    """Records ``(method, path, body)`` and pops queued :class:`ApiResponse`s.

    Queue responses with :meth:`queue`; a missing response is an error so a
    test can't silently make more calls than it expected.
    """

    def __init__(self, responses=()):
        self._responses: list[ApiResponse] = list(responses)
        self.calls: list[tuple[str, str, Any]] = []
        self.headers: dict[str, str] = {"authorization": "tok"}

    def queue(self, status: int, payload: Any = None) -> FakeApi:
        body = "" if payload is None else json.dumps(payload)
        self._responses.append(ApiResponse(status=status, headers={}, body=body))
        return self

    # -- the ApiCore surface ------------------------------------------------
    def execute(self, req: ApiRequest, *, raise_for_status: bool = True) -> ApiResponse:
        self.calls.append((req.method.upper(), req.path, req.body))
        if not self._responses:
            raise AssertionError(f"unexpected request: {req.method} {req.path}")
        r = self._responses.pop(0)
        if raise_for_status and not r.ok:
            from dexport.errors import ApiError

            raise ApiError(r.status, r.json() if r.body else None)
        return r

    def request(self, method, path, body=None, *, raise_for_status=True):
        return self.execute(ApiRequest(method, path, body), raise_for_status=raise_for_status)

    def get_json(self, path):
        return self.request("GET", path).json()

    def post_json(self, path, body):
        return self.request("POST", path, body).json()

    def me(self):
        return self.get_json("/users/@me")
