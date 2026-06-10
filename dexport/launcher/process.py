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
