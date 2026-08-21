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


def ensure_discord(
    port: int,
    *,
    binary_override: str | None = None,
    force_restart: bool = False,
    wait_timeout: float = 40.0,
    poll_interval: float = 0.75,
) -> str:
    """Guarantee a live CDP endpoint and return its HTTP base URL.

    Parameters
    ----------
    port:
        The remote-debugging port to use / expose.
    force_restart:
        When True, kill any running Discord first so it can be relaunched with
        the debug flag even if it is already open. This interrupts the user's
        current Discord session, so it is opt-in.
    """
    if is_cdp_alive(port):
        return cdp_http(port)

    binary = find_discord_binary(binary_override)

    if force_restart:
        kill_discord()
        # Give the single-instance lock time to release.
        if not _wait_until(lambda: not is_discord_running(), timeout=10, interval=0.5):
            # Launching now would just be forwarded to the surviving instance
            # (which has no debug port), so fail with a clear message instead.
            raise LauncherError(
                "Asked to restart Discord but it is still running after being "
                "signalled (SIGTERM then SIGKILL). Close it manually and retry."
            )

    launch_discord(binary, port)

    if _wait_until(lambda: is_cdp_alive(port), timeout=wait_timeout, interval=poll_interval):
        return cdp_http(port)

    raise LauncherError(
        f"Discord did not expose a CDP endpoint on port {port} within "
        f"{wait_timeout:.0f}s.\n"
        "If Discord is already running it was probably started without remote "
        "debugging (single-instance lock). Fully quit Discord and retry, or "
        "pass --restart to let dexport restart it for you."
    )


def _wait_until(condition: Callable[[], bool], *, timeout: float, interval: float) -> bool:
    """Poll ``condition`` until it is true (→ True) or ``timeout`` passes (→ False)."""
    deadline = time.time() + timeout
    while True:
        if condition():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(interval)
