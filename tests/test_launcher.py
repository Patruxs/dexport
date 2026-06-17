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


def test_linux_defaults_config_home_to_dot_config(linux):
    config_home, find = linux
    exe = touch(config_home / "discord" / "app-1.0.1" / "Discord")
    assert find(env={}) == [exe]


def test_linux_lists_ptb_and_canary_after_stable(linux):
    config_home, find = linux
    canary = touch(config_home / "discordcanary" / "app-1.0.1" / "DiscordCanary")
    ptb = touch(config_home / "discordptb" / "app-1.0.1" / "DiscordPTB")
    stable = touch(config_home / "discord" / "app-1.0.1" / "Discord")
    assert find() == [stable, ptb, canary]


def test_linux_includes_local_share_fallback_after_user_install(sandbox, linux):
    config_home, find = linux
    stable = touch(config_home / "discord" / "app-1.0.1" / "Discord")
    fallback = touch(sandbox / ".local" / "share" / "discord" / "Discord")
    assert find() == [stable, fallback]


def test_linux_includes_binary_found_on_path(sandbox, linux, monkeypatch):
    _, find = linux
    on_path = touch(sandbox / "bin" / "discord")
    monkeypatch.setattr(
        shutil, "which", lambda name, *_a, **_k: str(on_path) if name == "discord" else None
    )
    assert find() == [on_path]


def test_linux_deduplicates_path_lookup_already_listed(sandbox, linux, monkeypatch):
    _, find = linux
    fallback = touch(sandbox / ".local" / "share" / "discord" / "Discord")
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: str(fallback))
    assert find() == [fallback]


def test_linux_without_any_install_returns_empty(linux):
    _, find = linux
    assert find() == []


@pytest.mark.parametrize(
    ("probe", "expect_flatpak"),
    [
        pytest.param(lambda args: subprocess.CompletedProcess(args, 0), True, id="installed"),
        pytest.param(lambda args: subprocess.CompletedProcess(args, 1), False, id="absent"),
        pytest.param(raiser(subprocess.TimeoutExpired("flatpak", 5)), False, id="probe-hangs"),
    ],
)
def test_linux_flatpak_probe(linux, monkeypatch, probe, expect_flatpak):
    config_home, find = linux
    stable = touch(config_home / "discord" / "app-1.0.1" / "Discord")
    monkeypatch.setattr(
        shutil, "which", lambda name, *_a, **_k: "/usr/bin/flatpak" if name == "flatpak" else None
    )
    probes: list[list[str]] = []

    def fake_run(args, **_kwargs):
        probes.append(list(args))
        return probe(args)

    monkeypatch.setattr(subprocess, "run", fake_run)

    found = find(probe_flatpak=True)

    assert probes == [["/usr/bin/flatpak", "info", FLATPAK_APP_ID]]
    assert found == ([stable, FLATPAK_TARGET] if expect_flatpak else [stable])


def test_linux_probe_flatpak_false_spawns_nothing(linux, monkeypatch):
    _, find = linux
    monkeypatch.setattr(
        shutil, "which", lambda name, *_a, **_k: "/usr/bin/flatpak" if name == "flatpak" else None
    )
    monkeypatch.setattr(subprocess, "run", raiser(AssertionError("must not spawn flatpak")))
    assert find(probe_flatpak=False) == []


# --------------------------------------------------------------------------
# discovery.candidate_paths — Windows / macOS
# --------------------------------------------------------------------------


def test_windows_prefers_versioned_exe_then_update_stub(sandbox):
    local = sandbox / "Local"
    update = touch(local / "Discord" / "Update.exe")
    exe = touch(local / "Discord" / "app-1.0.5" / "Discord.exe")
    found = candidate_paths(
        system="Windows", home=sandbox / "home", env={"LOCALAPPDATA": str(local)}
    )
    assert found == [exe, update]


def test_windows_defaults_localappdata_under_home(sandbox):
    home = sandbox / "home"
    exe = touch(home / "AppData" / "Local" / "Discord" / "app-1.0.5" / "Discord.exe")
    assert candidate_paths(system="Windows", home=home, env={}) == [exe]


def test_darwin_finds_user_applications_bundle(sandbox):
    exe = touch(sandbox / "Applications" / "Discord.app" / "Contents" / "MacOS" / "Discord")
    assert candidate_paths(system="Darwin", home=sandbox) == [exe]


def test_darwin_without_bundle_returns_empty(sandbox):
    assert candidate_paths(system="Darwin", home=sandbox) == []


# --------------------------------------------------------------------------
# discovery.launch_command
# --------------------------------------------------------------------------


def test_launch_command_flatpak_runs_app_id():
    assert launch_command(FLATPAK_TARGET, 9222) == [
        "flatpak",
        "run",
        "com.discordapp.Discord",
        "--remote-debugging-port=9222",
    ]


@pytest.mark.parametrize("stub_name", ["Update.exe", "update.exe", "UPDATE.EXE"])
def test_launch_command_windows_update_stub_forwards_flag(stub_name):
    stub = Path("C:/Users/me/AppData/Local/Discord") / stub_name
    assert launch_command(stub, 9333) == [
        str(stub),
        "--processStart",
        "Discord.exe",
        "--process-start-args",
        "--remote-debugging-port=9333",
    ]


def test_launch_command_plain_binary():
    assert launch_command(Path("/opt/discord/Discord"), 9222) == [
        "/opt/discord/Discord",
        "--remote-debugging-port=9222",
    ]


# --------------------------------------------------------------------------
# discovery.find_discord_binary
# --------------------------------------------------------------------------


def test_find_discord_binary_rejects_missing_override(tmp_path):
    missing = tmp_path / "nope" / "Discord"
    with pytest.raises(LauncherError) as exc_info:
        find_discord_binary(str(missing))
    assert str(missing) in str(exc_info.value)


def test_find_discord_binary_accepts_flatpak_override_without_existence_check():
    assert find_discord_binary(str(FLATPAK_TARGET)) == FLATPAK_TARGET


def test_find_discord_binary_returns_existing_override(tmp_path):
    exe = touch(tmp_path / "Discord")
    assert find_discord_binary(str(exe)) == exe


@pytest.mark.parametrize("override", [None, ""], ids=["none", "empty"])
def test_find_discord_binary_without_candidates_points_at_env_var(monkeypatch, override):
    monkeypatch.setattr(discovery, "candidate_paths", lambda **_kwargs: [])
    with pytest.raises(LauncherError, match="DEXPORT_DISCORD_BINARY"):
        find_discord_binary(override)


def test_find_discord_binary_returns_best_candidate(monkeypatch):
    best, other = Path("/a/Discord"), Path("/b/Discord")
    monkeypatch.setattr(discovery, "candidate_paths", lambda **_kwargs: [best, other])
    assert find_discord_binary() == best


# --------------------------------------------------------------------------
# process.launch_discord
# --------------------------------------------------------------------------


def test_launch_discord_unix_detaches_into_new_session(popen_calls):
    launch_discord(FAKE_BINARY, PORT, system="Linux")

    assert len(popen_calls) == 1
    cmd, kwargs = popen_calls[0]
    assert cmd == [str(FAKE_BINARY), f"--remote-debugging-port={PORT}"]
    assert kwargs["start_new_session"] is True
    assert "creationflags" not in kwargs
    assert {kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]} == {subprocess.DEVNULL}


def test_launch_discord_windows_uses_detached_creation_flags(popen_calls):
    exe = Path("C:/Users/me/AppData/Local/Discord/app-1.0.5/Discord.exe")
    launch_discord(exe, PORT, system="Windows")

    assert len(popen_calls) == 1
    cmd, kwargs = popen_calls[0]
    assert cmd == [str(exe), f"--remote-debugging-port={PORT}"]
    assert kwargs["creationflags"] & DETACHED_PROCESS
    assert kwargs["creationflags"] & CREATE_NEW_PROCESS_GROUP
    assert "start_new_session" not in kwargs
    assert {kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]} == {subprocess.DEVNULL}


def test_launch_discord_wraps_os_error_in_launcher_error(monkeypatch):
    cause = FileNotFoundError(2, "No such file or directory")
    monkeypatch.setattr(subprocess, "Popen", raiser(cause))

    with pytest.raises(LauncherError) as exc_info:
        launch_discord(FAKE_BINARY, PORT, system="Linux")

    assert str(FAKE_BINARY) in str(exc_info.value)
    assert "No such file or directory" in str(exc_info.value)
    assert exc_info.value.__cause__ is cause


# --------------------------------------------------------------------------
# process.discord_pids / is_discord_running
# --------------------------------------------------------------------------


def test_discord_pids_merges_queries_and_excludes_own_process(monkeypatch):
    me, parent = os.getpid(), os.getppid()

    def run(args, timeout=10):
        if "-x" in args:  # exact-name query
            return subprocess.CompletedProcess(args, 0, f"{PID_A}\n{PID_B}\n{me}\n", "")
        return subprocess.CompletedProcess(args, 0, f"{PID_B}\n{PID_C}\n{parent}\nnot-a-pid\n", "")

    monkeypatch.setattr(process, "_run", run)
    assert discord_pids() == {PID_A, PID_B, PID_C}


def test_discord_pids_tolerates_one_failing_query(monkeypatch):
    def run(args, timeout=10):
        if "-f" in args:
            return None  # e.g. pgrep timed out
        return subprocess.CompletedProcess(args, 0, f"{PID_A}\n", "")

    monkeypatch.setattr(process, "_run", run)
    assert discord_pids() == {PID_A}


@pytest.mark.parametrize("system", ["Linux", "Windows"])
def test_is_discord_running_false_when_process_tools_unavailable(monkeypatch, system):
    monkeypatch.setattr(process, "_run", lambda *_a, **_k: None)
    assert discord_pids() == set()
    assert is_discord_running(system=system) is False


@pytest.mark.parametrize("system", ["Linux", "Windows"])
def test_is_discord_running_reflects_process_table(process_table, system):
    table = process_table({PID_A})
    assert is_discord_running(system=system) is True
    table.live.clear()
    assert is_discord_running(system=system) is False
    # Windows has no pgrep; Unix has no tasklist.
    tools = {cmd[0] for cmd in table.commands}
    assert tools == ({"tasklist"} if system == "Windows" else {"pgrep"})


# --------------------------------------------------------------------------
# process.kill_discord
# --------------------------------------------------------------------------


def test_kill_discord_sigterms_everything_then_sigkills_survivors(process_table):
    table = process_table({PID_A, PID_B}, stubborn={PID_B})

    kill_discord(system="Linux", grace=5.0)

    assert table.live == set()
    assert table.sent(signal.SIGTERM) == {PID_A, PID_B}
    assert table.sent(signal.SIGKILL) == {PID_B}
    assert [sig for _, sig in table.signals] == [signal.SIGTERM, signal.SIGTERM, signal.SIGKILL]
    assert table.clock.elapsed >= 5.0  # escalated only after the grace period


def test_kill_discord_returns_as_soon_as_processes_exit(process_table):
    table = process_table({PID_A, PID_B})

    kill_discord(system="Linux", grace=5.0)

    assert table.live == set()
    assert table.sent(signal.SIGKILL) == set()
    assert table.clock.sleeps == []  # gone on the first re-check: no waiting


def test_kill_discord_with_zero_grace_escalates_without_sleeping(process_table):
    table = process_table({PID_A, PID_B}, stubborn={PID_B})

    kill_discord(system="Linux", grace=0)

    assert table.live == set()
    assert table.sent(signal.SIGKILL) == {PID_B}
    assert table.clock.sleeps == []


def test_kill_discord_without_processes_signals_nothing(process_table):
    table = process_table()
    kill_discord(system="Linux", grace=5.0)
    assert table.signals == []
    assert table.clock.sleeps == []


def test_kill_discord_keeps_going_when_a_pid_cannot_be_signalled(process_table, monkeypatch):
    table = process_table({PID_A, PID_B})
    table_kill = table.kill

    def kill(pid, sig):
        if pid == PID_A:
            raise PermissionError(1, "Operation not permitted")
        table_kill(pid, sig)

    monkeypatch.setattr(os, "kill", kill)

    kill_discord(system="Linux", grace=1.0)  # must not raise

    assert PID_B not in table.live


def test_kill_discord_windows_uses_taskkill(process_table):
    table = process_table({PID_A})

    kill_discord(system="Windows")

    assert table.signals == []
    assert len(table.commands) == 1
    assert table.commands[0][0] == "taskkill"
    assert "Discord.exe" in table.commands[0]
    assert table.live == set()


# --------------------------------------------------------------------------
# is_cdp_alive / cdp_http
# --------------------------------------------------------------------------


def test_cdp_http_builds_loopback_url():
    assert cdp_http(9222) == "http://127.0.0.1:9222"


def test_is_cdp_alive_probes_json_version_and_accepts_200(monkeypatch):
    requests: list[tuple[str, float | None]] = []

    def fake_urlopen(url, timeout=None):
        requests.append((url, timeout))
        return FakeHttpResponse(200)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    assert is_cdp_alive(9333, timeout=0.25) is True
    assert requests == [("http://127.0.0.1:9333/json/version", 0.25)]


def test_is_cdp_alive_false_on_non_200(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: FakeHttpResponse(503))
    assert is_cdp_alive(9333) is False


@pytest.mark.parametrize(
    "failure",
    [urllib.error.URLError("connection refused"), ConnectionRefusedError(), TimeoutError()],
    ids=["urlerror", "refused", "timeout"],
)
def test_is_cdp_alive_false_when_endpoint_unreachable(monkeypatch, failure):
    monkeypatch.setattr(urllib.request, "urlopen", raiser(failure))
    assert is_cdp_alive(9333) is False


# --------------------------------------------------------------------------
# ensure_discord
# --------------------------------------------------------------------------


def test_ensure_discord_reuses_live_endpoint_without_launching(monkeypatch):
    stubs = LauncherStubs(monkeypatch, alive=[True])

    assert ensure_discord(PORT) == f"http://127.0.0.1:{PORT}"

    # Nothing else is touched: works even when no binary could be discovered.
    assert stubs.events == []


def test_ensure_discord_launches_found_binary_and_waits_for_endpoint(monkeypatch):
    stubs = LauncherStubs(monkeypatch, alive=[False, True])

    url = ensure_discord(PORT, binary_override="/custom/Discord", wait_timeout=1, poll_interval=0)

    assert url == f"http://127.0.0.1:{PORT}"
    assert stubs.events == [("find", "/custom/Discord"), ("launch", FAKE_BINARY, PORT)]


def test_ensure_discord_times_out_with_restart_hint(monkeypatch):
    stubs = LauncherStubs(monkeypatch, alive=[False])

    with pytest.raises(LauncherError) as exc_info:
        ensure_discord(PORT, wait_timeout=0, poll_interval=0)

    message = str(exc_info.value)
    assert "--restart" in message
    assert str(PORT) in message
    assert len(stubs.launches) == 1  # it did try


def test_ensure_discord_force_restart_refuses_to_launch_while_still_running(monkeypatch):
    stubs = LauncherStubs(monkeypatch, alive=[False], running=True)

    with pytest.raises(LauncherError, match="still running"):
        ensure_discord(PORT, force_restart=True, wait_timeout=0, poll_interval=0)

    assert ("kill",) in stubs.events
    assert stubs.launches == []


def test_ensure_discord_force_restart_kills_then_launches(monkeypatch):
    stubs = LauncherStubs(monkeypatch, alive=[False, True], running=False)

    url = ensure_discord(PORT, force_restart=True, wait_timeout=1, poll_interval=0)

    assert url == f"http://127.0.0.1:{PORT}"
    assert stubs.events == [("find", None), ("kill",), ("launch", FAKE_BINARY, PORT)]
