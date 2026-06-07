"""Tests for ``dexport.launcher``: binary discovery, process control, ensure_discord.

Everything runs offline against fakes: no Discord, no subprocesses, no
sockets, no real sleeping.

The discovery tests confine ``Path.exists`` to ``tmp_path`` because the source
probes hardcoded absolute install paths (``/usr/bin/discord``,
``/Applications/Discord.app``...) that may genuinely exist on a developer's
machine and would otherwise leak into the results.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from dexport.errors import LauncherError
from dexport.launcher import cdp_http, discovery, ensure_discord, is_cdp_alive, process
from dexport.launcher.discovery import (
    FLATPAK_APP_ID,
    FLATPAK_PREFIX,
    candidate_paths,
    find_discord_binary,
    launch_command,
    version_key,
)
from dexport.launcher.process import discord_pids, is_discord_running, kill_discord, launch_discord

PORT = 9222
FAKE_BINARY = Path("/fake/Discord")
FLATPAK_TARGET = Path(FLATPAK_PREFIX + FLATPAK_APP_ID)

# Win32 process creation flags (``subprocess`` only defines them on Windows).
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

# Above Linux's pid_max (4194304), so they can never collide with our own pid/ppid.
PID_A, PID_B, PID_C = 5_000_100, 5_000_200, 5_000_300


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def raiser(exc: BaseException):
    """Return a callable that raises ``exc`` whatever it is called with."""

    def _raise(*_args, **_kwargs):
        raise exc

    return _raise


class FakeClock:
    """Deterministic ``time.time``/``time.sleep`` pair: sleeping advances the clock."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.start = start
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if len(self.sleeps) > 10_000:
            raise AssertionError("runaway polling loop: sleep called 10k times")

    @property
    def elapsed(self) -> float:
        return self.now - self.start


class FakeProcessTable:
    """In-memory stand-in for pgrep/tasklist/taskkill and ``os.kill``.

    PIDs in ``stubborn`` ignore SIGTERM (only SIGKILL removes them), so the
    escalation path can be exercised without real processes.
    """

    def __init__(self, pids=(), *, stubborn=()) -> None:
        self.live: set[int] = set(pids)
        self.stubborn: set[int] = set(stubborn)
        self.signals: list[tuple[int, int]] = []
        self.commands: list[list[str]] = []
        self.clock = FakeClock()

    def run(self, args, timeout=10):
        self.commands.append(list(args))
        tool = args[0]
        if tool == "pgrep":
            out = "".join(f"{pid}\n" for pid in sorted(self.live))
            return subprocess.CompletedProcess(args, 0 if self.live else 1, out, "")
        if tool == "tasklist":
            out = "Discord.exe  1234 Console" if self.live else "INFO: No tasks are running."
            return subprocess.CompletedProcess(args, 0, out, "")
        if tool == "taskkill":
            self.live.clear()
            return subprocess.CompletedProcess(args, 0, "SUCCESS", "")
        raise AssertionError(f"unexpected command: {args}")

    def kill(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))
        if pid not in self.live:
            raise ProcessLookupError(pid)
        if sig == signal.SIGKILL or pid not in self.stubborn:
            self.live.discard(pid)

    def sent(self, sig: int) -> set[int]:
        return {pid for pid, s in self.signals if s == sig}


class FakeHttpResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class LauncherStubs:
    """Replaces ``ensure_discord``'s collaborators and records calls, in order.

    ``alive`` is the sequence of ``is_cdp_alive`` answers; the last one repeats.
    """

    def __init__(self, monkeypatch, *, alive, running=False, binary=FAKE_BINARY) -> None:
        self._alive = list(alive)
        self.running = running
        self.binary = binary
        self.events: list[tuple] = []
        self.clock = FakeClock()
        monkeypatch.setattr("dexport.launcher.is_cdp_alive", self._is_cdp_alive)
        monkeypatch.setattr("dexport.launcher.find_discord_binary", self._find)
        monkeypatch.setattr("dexport.launcher.kill_discord", self._kill)
        monkeypatch.setattr("dexport.launcher.is_discord_running", self._is_running)
        monkeypatch.setattr("dexport.launcher.launch_discord", self._launch)
        monkeypatch.setattr("dexport.launcher.time.time", self.clock.time)
        monkeypatch.setattr("dexport.launcher.time.sleep", self.clock.sleep)

    def _is_cdp_alive(self, port, timeout=1.5):
        return self._alive.pop(0) if len(self._alive) > 1 else self._alive[0]

    def _find(self, override=None):
        self.events.append(("find", override))
        return self.binary

    def _kill(self, *_args, **_kwargs):
        self.events.append(("kill",))

    def _is_running(self, *_args, **_kwargs):
        return self.running

    def _launch(self, binary, port, system=None):
        self.events.append(("launch", binary, port))

    @property
    def launches(self) -> list[tuple]:
        return [e for e in self.events if e[0] == "launch"]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Confine discovery to ``tmp_path``: system paths never "exist", PATH is empty."""
    real_exists = Path.exists

    def exists(self, *args, **kwargs):
        return self.is_relative_to(tmp_path) and real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: None)
    return tmp_path


@pytest.fixture
def linux(sandbox):
    """Run ``candidate_paths`` for Linux against the sandbox; returns (config_home, call)."""
    config_home = sandbox / ".config"

    def call(*, env=None, probe_flatpak=False):
        env = {"XDG_CONFIG_HOME": str(config_home)} if env is None else env
        return candidate_paths(system="Linux", home=sandbox, env=env, probe_flatpak=probe_flatpak)

    return config_home, call


@pytest.fixture
def popen_calls(monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    def fake_popen(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls


@pytest.fixture
def process_table(monkeypatch):
    """Factory: install a :class:`FakeProcessTable` behind ``_run``/``os.kill``/``time``."""

    def install(pids=(), *, stubborn=()):
        table = FakeProcessTable(pids, stubborn=stubborn)
        monkeypatch.setattr(process, "_run", table.run)
        monkeypatch.setattr(os, "kill", table.kill)
        monkeypatch.setattr("dexport.launcher.process.time.time", table.clock.time)
        monkeypatch.setattr("dexport.launcher.process.time.sleep", table.clock.sleep)
        return table

    return install


# --------------------------------------------------------------------------
# discovery.version_key
# --------------------------------------------------------------------------


def test_version_key_orders_numerically_not_lexicographically():
    # A plain string sort would put "app-1.0.10000" before "app-1.0.9000".
    assert version_key(Path("/opt/app-1.0.10000")) == [1, 0, 10000]
    assert version_key(Path("app-1.0.10000")) > version_key(Path("app-1.0.9000"))


def test_version_key_of_non_numeric_name_is_zero():
    assert version_key(Path("app-nightly")) == [0]


# --------------------------------------------------------------------------
# discovery.candidate_paths — Linux
# --------------------------------------------------------------------------


def test_linux_prefers_numerically_newest_versioned_build(linux):
    config_home, find = linux
    old = touch(config_home / "discord" / "app-1.0.9000" / "Discord")
    new = touch(config_home / "discord" / "app-1.0.10000" / "Discord")
    assert find() == [new, old]


def test_linux_skips_versioned_dir_without_binary(linux):
    config_home, find = linux
    (config_home / "discord" / "app-1.0.10000").mkdir(parents=True)  # update in progress
    old = touch(config_home / "discord" / "app-1.0.9000" / "Discord")
    assert find() == [old]
