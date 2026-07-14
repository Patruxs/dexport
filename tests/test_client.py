"""``Dexport.acquire`` / ``close``: the facade that wires the pipeline together.

The three side-effecting steps (launcher, CDP attach, header snapshot) are
replaced with fakes that record what they were called with; everything below
them (ApiCore, RateLimiter, Resolver, cache file) is real.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from conftest import FakeSession, resp

from dexport.client import Dexport
from dexport.config import Paths, Settings, load_cache, save_cache
from dexport.errors import HeaderCaptureError, LauncherError

CACHE = {"guilds": [{"id": "1", "name": "cú đêm"}], "channels": {}}


class FakeClientSession(FakeSession):
    """conftest's fetch-faking session plus the ``close()`` the client relies on."""

    def __init__(self, responses=()):
        super().__init__(responses)
        self.closed = False

    def close(self) -> None:
        self.closed = True


@dataclass
class Pipeline:
    """What the patched pipeline steps recorded / what they should do."""

    session: FakeClientSession = field(default_factory=FakeClientSession)
    headers: dict[str, str] = field(default_factory=lambda: {"authorization": "tok"})
    ensure_error: Exception | None = None
    capture_error: Exception | None = None
    ensure_calls: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    connect_calls: list[str] = field(default_factory=list)
    capture_calls: list[Any] = field(default_factory=list)


@pytest.fixture
def pipeline(monkeypatch) -> Pipeline:
    p = Pipeline()

    def fake_ensure_discord(port: int, **kwargs: Any) -> str:
        p.ensure_calls.append((port, kwargs))
        if p.ensure_error is not None:
            raise p.ensure_error
        return f"http://127.0.0.1:{port}"

    class FakeSessionClass:
        @classmethod
        def connect(cls, endpoint: str) -> FakeClientSession:
            p.connect_calls.append(endpoint)
            return p.session

    def fake_capture_headers(session: Any, **kwargs: Any) -> dict[str, str]:
        p.capture_calls.append(session)
        if p.capture_error is not None:
            raise p.capture_error
        return dict(p.headers)

    monkeypatch.setattr("dexport.client.ensure_discord", fake_ensure_discord)
    monkeypatch.setattr("dexport.client.Session", FakeSessionClass)
    monkeypatch.setattr("dexport.client.capture_headers", fake_capture_headers)
    return p


def _settings(**overrides: Any) -> Settings:
    base = {
        "port": 5555,
        "discord_binary": "/opt/Discord/Discord",
        "floor_delay_min": 0.0,
        "floor_delay_max": 0.0,
    }
    return Settings(**{**base, **overrides})


# --------------------------------------------------------------------------
# acquire: happy path
# --------------------------------------------------------------------------


def test_acquire_passes_settings_to_launcher(pipeline):
    Dexport.acquire(settings=_settings(), force_restart=True)
    assert pipeline.ensure_calls == [
        (5555, {"binary_override": "/opt/Discord/Discord", "force_restart": True})
    ]


def test_acquire_force_restart_defaults_to_false(pipeline):
    Dexport.acquire(settings=_settings(discord_binary=None))
    assert pipeline.ensure_calls == [(5555, {"binary_override": None, "force_restart": False})]


def test_acquire_connects_to_the_launcher_endpoint_and_snapshots_it(pipeline):
    dx = Dexport.acquire(settings=_settings())
    assert pipeline.connect_calls == ["http://127.0.0.1:5555"]
    assert pipeline.capture_calls == [pipeline.session]
    assert dx.session is pipeline.session


def test_acquire_gives_api_the_captured_headers(pipeline):
    pipeline.headers = {"authorization": "tok", "x-super-properties": "abc"}
    dx = Dexport.acquire(settings=_settings())
    assert dx.api.headers == {"authorization": "tok", "x-super-properties": "abc"}
    assert dx.api.session is pipeline.session
