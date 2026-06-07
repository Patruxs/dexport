"""Find the Discord desktop binary and build its launch command, per OS.

Everything here is pure (no processes spawned) apart from the optional
``flatpak info`` probe on Linux, so it can be unit-tested with a fake home
directory. To support a new install location, add it to the matching
``_*_candidates`` function.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from ..errors import LauncherError

#: Pseudo-path used to mean "launch via ``flatpak run <app-id>``".
FLATPAK_PREFIX = "flatpak:"
FLATPAK_APP_ID = "com.discordapp.Discord"

#: Linux updater installs live under ``$XDG_CONFIG_HOME/<dir>/app-*/<exe>``.
_LINUX_USER_INSTALLS = (
    ("discord", "Discord"),
    ("discordptb", "DiscordPTB"),
    ("discordcanary", "DiscordCanary"),
)

_LINUX_SYSTEM_PATHS = (
    Path("/usr/share/discord/Discord"),
    Path("/opt/discord/Discord"),
    Path("/opt/Discord/Discord"),
)


def version_key(path: Path) -> list[int]:
    """Numeric version tuple parsed from an ``app-1.0.10000`` style dir name."""
    return [int(x) for x in re.findall(r"\d+", path.name)] or [0]


def _newest_versioned(base: Path, exe_name: str) -> list[Path]:
    """``base/app-*/exe_name`` that exist, newest version first.

    Sorts by the *numeric* version so ``app-1.0.10000`` beats ``app-1.0.9000``
    (a lexicographic sort would pick the older build).
    """
    if not base.exists():
        return []
    out = []
    for versioned in sorted(base.glob("app-*"), key=version_key, reverse=True):
        exe = versioned / exe_name
        if exe.exists():
            out.append(exe)
    return out


def _windows_candidates(home: Path, env: Mapping[str, str]) -> list[Path]:
    local = env.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
    base = Path(local) / "Discord"
    # Prefer the newest versioned app-*/Discord.exe, else the Update.exe stub.
    out = _newest_versioned(base, "Discord.exe")
    update = base / "Update.exe"
    if update.exists():
        out.append(update)
    return out


def _macos_candidates(home: Path) -> list[Path]:
    out = []
    for root in (Path("/Applications"), home / "Applications"):
        exe = root / "Discord.app" / "Contents" / "MacOS" / "Discord"
        if exe.exists():
            out.append(exe)
    return out
