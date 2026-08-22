"""Start, find and stop the Discord desktop process.

On Unix we signal specific PIDs rather than using ``pkill -f`` with a
substring, which would match — and kill — unrelated processes whose command
line merely contains the pattern.
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path

from ..errors import LauncherError
from .discovery import FLATPAK_APP_ID, launch_command

# Windows-only subprocess flags; 0 elsewhere so the module imports anywhere.
_DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def _run(args: list[str], timeout: float = 10) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def discord_pids() -> set[int]:
    """PIDs of running Discord processes (Unix), excluding this tool and its parent.

    Uses an exact-name match plus a Flatpak-app match. Our own PID / parent PID
    are excluded so that passing ``--binary flatpak:com.discordapp.Discord`` on
    the command line (which puts that string in *our* argv) can't make us signal
    ourselves.
    """
    exclude = {os.getpid(), os.getppid()}
    found: set[int] = set()
    for args in (["pgrep", "-x", "Discord"], ["pgrep", "-f", FLATPAK_APP_ID]):
        res = _run(args)
        if res is None:
            continue
        for token in (res.stdout or "").split():
            if token.isdigit():
                pid = int(token)
                if pid not in exclude:
                    found.add(pid)
    return found


def is_discord_running(system: str | None = None) -> bool:
    system = system or platform.system()
    if system == "Windows":
        res = _run(["tasklist", "/FI", "IMAGENAME eq Discord.exe"])
        return res is not None and "Discord.exe" in (res.stdout or "")
    return bool(discord_pids())


def _signal_pids(pids: set[int], sig: int) -> None:
    for pid in pids:
        with suppress(OSError):  # already exited / not ours
            os.kill(pid, sig)


def kill_discord(system: str | None = None, grace: float = 5.0) -> None:
    """Best-effort terminate running Discord processes (opt-in restart path).

    Unix: SIGTERM, then SIGKILL for anything still alive after ``grace`` s.
    """
    system = system or platform.system()
    if system == "Windows":
        _run(["taskkill", "/F", "/IM", "Discord.exe", "/T"], timeout=15)
        return

    pids = discord_pids()
    if not pids:
        return
    _signal_pids(pids, signal.SIGTERM)
    deadline = time.time() + grace
    while time.time() < deadline:
        if not discord_pids():
            return
        time.sleep(0.4)
    # Escalate: anything still alive after the grace period gets SIGKILL.
    _signal_pids(discord_pids(), signal.SIGKILL)


def launch_discord(binary: Path, port: int, system: str | None = None) -> None:
    """Spawn Discord detached (it must outlive us) with the remote-debugging flag."""
    system = system or platform.system()
    cmd = launch_command(binary, port)
    kwargs: dict[str, object] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if system == "Windows":
        kwargs["creationflags"] = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)  # type: ignore[call-overload]
    except OSError as exc:
        raise LauncherError(f"Failed to launch Discord ({cmd[0]}): {exc}") from exc
