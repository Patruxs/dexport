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


TOS_NOTICE = (
    "dexport automates a [b]user[/b] account, which Discord's Terms of Service "
    "do not allow. The penalty for a self-bot is account termination, and it is "
    "permanent.\n\n"
    "Keep it personal and low-volume — your own history, your own messages — "
    "and use it at your own risk. This notice is shown once; the full caveat is "
    "in the README."
)


def warn_tos_once(paths: Paths | None = None) -> None:
    """Print the self-bot notice the first time dexport drives the account.

    A marker file under ``$DEXPORT_HOME`` keeps it to once per install — the
    condensed version stays in ``dexport --help`` for every run. Written to
    stderr so it never contaminates piped output.
    """
    marker = (paths or Paths.default()).notice
    if marker.exists():
        return
    err_console.print(
        Panel(TOS_NOTICE, title="[yellow]Before you use this[/yellow]", border_style="yellow")
    )
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("Terms-of-Service notice shown.\n", encoding="utf-8")
    except OSError:
        pass  # An unwritable home just means the notice shows again next time.


@contextmanager
def connect(ctx: typer.Context) -> Iterator[Dexport]:
    """Acquire a Discord session for the duration of the block.

    Any :class:`DexportError` raised while acquiring *or inside the block* is
    reported as a one-line error with exit code 1; the session is always
    released and the resolver cache saved.
    """
    warn_tos_once()
    opts: ConnectionOptions = ctx.obj or ConnectionOptions()
    try:
        with Dexport.acquire(settings=opts.settings(), force_restart=opts.restart) as dx:
            yield dx
    except DexportError as exc:
        fail(str(exc))


# --------------------------------------------------------------------------
# Target selection (guild/channel by name or ID)
# --------------------------------------------------------------------------

GuildOpt = Annotated[
    str | None,
    typer.Option("-g", "--guild", help="Guild (server) name; fuzzy, diacritics-insensitive."),
]
ChannelOpt = Annotated[
    str | None,
    typer.Option("-c", "--channel", help="Channel name; fuzzy, diacritics-insensitive."),
]
GuildIdOpt = Annotated[str | None, typer.Option("--guild-id", help="Guild ID (skips lookup).")]
ChannelIdOpt = Annotated[
    str | None, typer.Option("--channel-id", help="Channel ID (skips lookup).")
]
YesOpt = Annotated[bool, typer.Option("-y", "--yes", help="Skip confirmation.")]
DryRunOpt = Annotated[bool, typer.Option("--dry-run", help="Show the request, don't send.")]


@dataclass(frozen=True)
class Target:
    """Where a command should act. IDs win over names (for scripting)."""

    guild: str | None = None
    channel: str | None = None
    guild_id: str | None = None
    channel_id: str | None = None


def resolve_guild(
    dx: Dexport,
    guild: str | None,
    guild_id: str | None,
    *,
    missing: str = "Provide -g/--guild or --guild-id.",
) -> tuple[str, str]:
    """Return ``(guild_id, human_label)``."""
    if guild_id is not None:
        return guild_id, guild_id
    if not guild:
        fail(missing)
    g = dx.resolver.resolve_guild(guild)
    return g["id"], g.get("name", g["id"])


def resolve_channel(dx: Dexport, target: Target) -> tuple[str, str]:
    """Return ``(channel_id, human_label)``."""
    if target.channel_id:
        return target.channel_id, f"channel {target.channel_id}"
    if not target.channel:
        fail("Provide a channel with -c/--channel or --channel-id.")
    gid, glabel = resolve_guild(
        dx,
        target.guild,
        target.guild_id,
        missing="Provide a guild with -g/--guild or --guild-id (or use --channel-id).",
    )
    c = dx.resolver.resolve_channel(gid, target.channel)
    return c["id"], f"{glabel} #{c.get('name', c['id'])}"
