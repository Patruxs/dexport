"""Plumbing shared by every command module.

* :data:`console` / :func:`fail` — output and clean error exits.
* :class:`ConnectionOptions` + :func:`connect` — global flags → a live
  :class:`~dexport.client.Dexport`, with expected errors turned into
  ``error: ...`` + exit 1 in one place.
* :class:`Target` + :func:`resolve_channel` — the ``-g/-c/--guild-id/--channel-id``
  quartet every channel command accepts.
* :func:`run_write` — the one code path for all write verbs
  (dry-run → resolve → confirm → pause → execute).
* :func:`warn_tos_once` — the self-bot notice, shown the first time dexport
  actually drives the account.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.panel import Panel

from ..api import ApiRequest, ApiResponse
from ..client import Dexport
from ..config import Paths, Settings
from ..errors import ApiError, DexportError

console = Console()
err_console = Console(stderr=True)


def fail(msg: str) -> NoReturn:
    """Print ``error: msg`` to stderr and exit 1."""
    err_console.print(f"[red]error:[/red] {msg}")
    raise typer.Exit(1)


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectionOptions:
    """The global flags from the root callback (``dexport --port ... <cmd>``)."""

    port: int | None = None
    restart: bool = False
    binary: str | None = None

    def settings(self, paths: Paths | None = None) -> Settings:
        """Effective settings: **CLI flag > env var > config.json > default**."""
        return Settings.load(paths).with_overrides(port=self.port, discord_binary=self.binary)
