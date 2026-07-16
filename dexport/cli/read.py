"""Read-only verbs: whoami / guilds / channels / read / export."""

from __future__ import annotations

from typing import Annotated

import typer

from ..messages import fetch_history
from ..render import (
    EXPORT_EXTENSIONS,
    export_to_file,
    get_exporter,
    render_terminal,
    summarize_author,
)
from .common import (
    ChannelIdOpt,
    ChannelOpt,
    GuildIdOpt,
    GuildOpt,
    Target,
    connect,
    console,
    fail,
    resolve_channel,
    resolve_guild,
)

commands = typer.Typer()

RefreshOpt = Annotated[bool, typer.Option("--refresh", help="Ignore cache and refetch.")]


@commands.command()
def whoami(ctx: typer.Context) -> None:
    """Verify the session by printing your own account."""
    with connect(ctx) as dx:
        me = dx.api.me()
    console.print(
        f"[green]Logged in as[/green] {summarize_author(me)}  [dim]({me.get('id')})[/dim]"
    )


@commands.command()
def guilds(ctx: typer.Context, refresh: RefreshOpt = False) -> None:
    """List the servers your account is in."""
    with connect(ctx) as dx:
        data = dx.resolver.guilds(refresh=refresh)
    console.rule(f"{len(data)} guilds")
    for g in sorted(data, key=lambda x: x.get("name", "").lower()):
        console.print(f"{g['id']}  [cyan]{g.get('name', '')}[/cyan]")


@commands.command()
def channels(
    ctx: typer.Context,
    guild: GuildOpt = None,
    guild_id: GuildIdOpt = None,
    refresh: RefreshOpt = False,
) -> None:
    """List channels in a server."""
    with connect(ctx) as dx:
        gid, title = resolve_guild(dx, guild, guild_id)
        data = dx.resolver.channels(gid, refresh=refresh)
    console.rule(f"{title}: {len(data)} channels")
    for c in data:
        console.print(
            f"{c['id']}  [cyan]#{c.get('name', '')}[/cyan] [dim]type={c.get('type')}[/dim]"
        )
