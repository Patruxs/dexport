"""Session lifecycle: make sure Discord is running with a live CDP port.

Strategy (see docs/ARCHITECTURE.md):

1. Is the CDP port alive? (``GET /json/version`` returns 200) -> use it.
2. If not, find the Discord binary for this OS (:mod:`.discovery`) and
   (re)launch it with ``--remote-debugging-port=<port>`` (:mod:`.process`),
   then poll ``/json/version`` until it answers or we time out.

Because Discord uses a single-instance lock, an *already running* client that
was started without the debug flag will simply refuse a second launch. In that
case dexport tells the user to quit Discord (or pass ``force_restart=True`` to
let dexport kill and relaunch it) rather than silently doing nothing.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable

from ..errors import LauncherError
from .discovery import candidate_paths, find_discord_binary, launch_command
from .process import is_discord_running, kill_discord, launch_discord

__all__ = [
    "candidate_paths",
    "cdp_http",
    "ensure_discord",
    "find_discord_binary",
    "is_cdp_alive",
    "is_discord_running",
    "kill_discord",
    "launch_command",
    "launch_discord",
]


def cdp_http(port: int) -> str:
    """Return the HTTP base URL for the CDP endpoint on ``port``."""
    return f"http://127.0.0.1:{port}"


def is_cdp_alive(port: int, timeout: float = 1.5) -> bool:
    """True when the DevTools ``/json/version`` endpoint answers with 200."""
    url = f"{cdp_http(port)}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - localhost
            return bool(resp.status == 200)
    except (urllib.error.URLError, OSError, ValueError):
        return False
