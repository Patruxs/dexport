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
    """conftest's fetch-faking session plus the ``close()``/``origin`` the client relies on."""

    def __init__(self, responses=(), origin="https://discord.com"):
        super().__init__(responses)
        self.origin = origin
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


def test_acquire_gives_api_the_page_origin(pipeline):
    """The in-page fetch must stay same-origin with the client; see api.rebase_url."""
    pipeline.session = FakeClientSession(origin="https://discordapp.com")
    dx = Dexport.acquire(settings=_settings())
    assert dx.api.origin == "https://discordapp.com"


def test_acquire_configures_limiter_floor_from_settings(pipeline):
    dx = Dexport.acquire(settings=_settings(floor_delay_min=0.1, floor_delay_max=0.4))
    assert dx.api.limiter.floor_min == 0.1
    assert dx.api.limiter.floor_max == 0.4


def test_acquire_loads_resolver_cache_from_dexport_home(pipeline, dexport_home):
    save_cache(CACHE)
    assert (dexport_home / "cache.json").exists()

    dx = Dexport.acquire(settings=_settings())
    assert dx.resolver.cache["guilds"] == CACHE["guilds"]
    assert dx.resolver.api is dx.api


def test_acquire_with_no_cache_file_starts_empty(pipeline):
    dx = Dexport.acquire(settings=_settings())
    assert dx.resolver.cache == {"guilds": None, "channels": {}}


def test_acquire_uses_capture_headers_as_the_refresh_hook(pipeline):
    """The refresh hook must be the real capture step, not a stale copy."""
    pipeline.headers = {"authorization": "old"}
    pipeline.session = FakeClientSession(
        [
            resp(401, json.dumps({"message": "401: Unauthorized"})),
            resp(200, json.dumps({"id": "42"})),
        ]
    )
    dx = Dexport.acquire(settings=_settings())
    pipeline.headers = {"authorization": "new"}

    assert dx.api.me() == {"id": "42"}
    # capture_headers ran once during acquire and once for the 401.
    assert pipeline.capture_calls == [pipeline.session, pipeline.session]
    assert pipeline.session.calls[1]["headers"]["authorization"] == "new"


# --------------------------------------------------------------------------
# acquire: settings / paths defaults
# --------------------------------------------------------------------------


def test_acquire_without_settings_loads_config_from_dexport_home(pipeline):
    Settings(port=4321).save()
    Dexport.acquire()
    assert pipeline.ensure_calls[0][0] == 4321


def test_acquire_without_settings_applies_env_overrides(pipeline, monkeypatch):
    Settings(port=4321, discord_binary="/from/file").save()
    monkeypatch.setenv("DEXPORT_PORT", "5000")
    monkeypatch.setenv("DEXPORT_DISCORD_BINARY", "/from/env")
    Dexport.acquire()
    assert pipeline.ensure_calls == [
        (5000, {"binary_override": "/from/env", "force_restart": False})
    ]


def test_acquire_honours_explicit_paths_for_config_and_cache(pipeline, tmp_path, dexport_home):
    alt = Paths(tmp_path / "alt-home")
    Settings(port=7777).save(alt)
    save_cache(CACHE, alt)

    dx = Dexport.acquire(paths=alt)
    assert pipeline.ensure_calls[0][0] == 7777
    assert dx.resolver.cache["guilds"] == CACHE["guilds"]

    dx.resolver.cache["guilds"] = [{"id": "2", "name": "moved"}]
    dx.close()
    assert load_cache(alt)["guilds"] == [{"id": "2", "name": "moved"}]
    assert not (dexport_home / "cache.json").exists()


# --------------------------------------------------------------------------
# acquire: failure paths
# --------------------------------------------------------------------------


def test_acquire_closes_session_when_header_capture_fails(pipeline):
    pipeline.capture_error = HeaderCaptureError("Never observed an authorized /api request")
    with pytest.raises(HeaderCaptureError, match="Never observed"):
        Dexport.acquire(settings=_settings())
    assert pipeline.session.closed


def test_acquire_propagates_launcher_error_before_connecting(pipeline):
    pipeline.ensure_error = LauncherError("Discord binary not found")
    with pytest.raises(LauncherError, match="not found"):
        Dexport.acquire(settings=_settings())
    assert pipeline.connect_calls == []
    assert pipeline.capture_calls == []
    assert not pipeline.session.closed


def test_acquire_closes_session_when_a_later_step_fails(pipeline, monkeypatch):
    monkeypatch.setattr("dexport.client.load_cache", lambda paths: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        Dexport.acquire(settings=_settings())
    assert pipeline.session.closed


# --------------------------------------------------------------------------
# close / save / context manager
# --------------------------------------------------------------------------


def test_close_persists_resolver_cache_and_closes_session(pipeline, dexport_home):
    save_cache(CACHE)
    dx = Dexport.acquire(settings=_settings())
    dx.resolver.cache["guilds"] = [{"id": "9", "name": "brand new"}]
    dx.resolver.cache["channels"]["9"] = [
        {"id": "90", "name": "general", "type": 0, "parent_id": None}
    ]

    dx.close()

    assert load_cache() == dx.resolver.cache
    assert (
        json.loads((dexport_home / "cache.json").read_text(encoding="utf-8")) == dx.resolver.cache
    )
    assert pipeline.session.closed


def test_save_persists_without_closing(pipeline):
    dx = Dexport.acquire(settings=_settings())
    dx.resolver.cache["guilds"] = [{"id": "3", "name": "saved"}]
    dx.save()
    assert load_cache()["guilds"] == [{"id": "3", "name": "saved"}]
    assert not pipeline.session.closed


def test_close_still_closes_session_when_save_fails(pipeline, monkeypatch):
    def broken_save(cache, paths=None):
        raise OSError("disk full")

    monkeypatch.setattr("dexport.client.save_cache", broken_save)
    dx = Dexport.acquire(settings=_settings())
    with pytest.raises(OSError, match="disk full"):
        dx.close()
    assert pipeline.session.closed


def test_context_manager_yields_handle_and_closes_on_exit(pipeline, dexport_home):
    with Dexport.acquire(settings=_settings()) as dx:
        assert isinstance(dx, Dexport)
        dx.resolver.cache["guilds"] = [{"id": "5", "name": "ctx"}]
        assert not pipeline.session.closed
    assert pipeline.session.closed
    assert load_cache()["guilds"] == [{"id": "5", "name": "ctx"}]


def test_context_manager_closes_on_exception(pipeline):
    with pytest.raises(RuntimeError, match="boom"), Dexport.acquire(settings=_settings()):
        raise RuntimeError("boom")
    assert pipeline.session.closed
