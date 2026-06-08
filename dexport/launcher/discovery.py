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


def _linux_candidates(home: Path, env: Mapping[str, str], *, probe_flatpak: bool) -> list[Path]:
    # Discord's Linux updater installs the *real* binary under the user's
    # config dir (e.g. ~/.config/discord/app-1.0.155/Discord). Prefer it:
    # the /usr/bin/discord launcher is a bootstrap shell script that goes
    # through an updater (and a zenity dialog when detached), which does not
    # reliably pass --remote-debugging-port through to the app.
    config_home = Path(env.get("XDG_CONFIG_HOME", str(home / ".config")))
    out: list[Path] = []
    for app_dir_name, exe_name in _LINUX_USER_INSTALLS:
        out.extend(_newest_versioned(config_home / app_dir_name, exe_name))
    # System install locations and the wrapper (bootstrap) as fallbacks.
    for cand in (
        *_LINUX_SYSTEM_PATHS,
        home / ".local" / "share" / "discord" / "Discord",
        Path("/usr/bin/discord"),
        Path("/usr/local/bin/discord"),
    ):
        if cand.exists():
            out.append(cand)
    which = shutil.which("discord") or shutil.which("Discord")
    if which:
        out.append(Path(which))
    if probe_flatpak:
        flatpak = shutil.which("flatpak")
        if flatpak and _flatpak_has_discord(flatpak):
            out.append(Path(FLATPAK_PREFIX + FLATPAK_APP_ID))
    return out


def candidate_paths(
    *,
    system: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    probe_flatpak: bool = True,
) -> list[Path]:
    """Plausible Discord launch targets for this machine, best first.

    ``system``/``home``/``env`` default to the real platform, home dir and
    environment; tests pass fakes.
    """
    system = system or platform.system()
    home = home or Path.home()
    env = os.environ if env is None else env

    if system == "Windows":
        found = _windows_candidates(home, env)
    elif system == "Darwin":
        found = _macos_candidates(home)
    else:  # Linux / *nix
        found = _linux_candidates(home, env, probe_flatpak=probe_flatpak)

    # De-duplicate, preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for p in found:
        key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _flatpak_has_discord(flatpak: str) -> bool:
    try:
        res = subprocess.run(
            [flatpak, "info", FLATPAK_APP_ID],
            capture_output=True,
            timeout=5,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def find_discord_binary(override: str | None = None) -> Path:
    """Return the best Discord launch target, or raise :class:`LauncherError`."""
    if override:
        p = Path(override)
        if not str(p).startswith(FLATPAK_PREFIX) and not p.exists():
            raise LauncherError(f"Configured Discord binary does not exist: {override}")
        return p
    candidates = candidate_paths()
    if not candidates:
        raise LauncherError(
            "Could not find the Discord desktop client. Install it, or set "
            'the binary path in ~/.dexport/config.json ("discord_binary") or '
            "the DEXPORT_DISCORD_BINARY environment variable."
        )
    return candidates[0]


def launch_command(binary: Path, port: int) -> list[str]:
    """Build the argv to start Discord with remote debugging enabled."""
    flag = f"--remote-debugging-port={port}"
    text = str(binary)

    if text.startswith(FLATPAK_PREFIX):
        app_id = text.split(":", 1)[1]
        return ["flatpak", "run", app_id, flag]

    if binary.name.lower() == "update.exe":
        # Windows stub launcher: pass args through to the real Discord.exe.
        return [text, "--processStart", "Discord.exe", "--process-start-args", flag]

    return [text, flag]
