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


@commands.command()
def read(
    ctx: typer.Context,
    guild: GuildOpt = None,
    channel: ChannelOpt = None,
    guild_id: GuildIdOpt = None,
    channel_id: ChannelIdOpt = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many recent messages.")] = 50,
) -> None:
    """Print recent messages from a channel."""
    with connect(ctx) as dx:
        cid, label = resolve_channel(dx, Target(guild, channel, guild_id, channel_id))
        messages = fetch_history(dx.api, cid, limit)
    render_terminal(messages, title=label, console=console)


@commands.command()
def export(
    ctx: typer.Context,
    guild: GuildOpt = None,
    channel: ChannelOpt = None,
    guild_id: GuildIdOpt = None,
    channel_id: ChannelIdOpt = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many recent messages.")] = 100,
    fmt: Annotated[str, typer.Option("--format", "-f", help="md or json.")] = "md",
    output: Annotated[str | None, typer.Option("-o", "--output", help="Output file path.")] = None,
) -> None:
    """Export channel history to a Markdown or JSON file."""
    try:
        get_exporter(fmt)  # fail fast, before launching/attaching to Discord
    except ValueError as exc:
        fail(str(exc))
    with connect(ctx) as dx:
        cid, label = resolve_channel(dx, Target(guild, channel, guild_id, channel_id))
        messages = fetch_history(
            dx.api,
            cid,
            limit,
            on_page=lambda n: console.print(f"[dim]fetched {n}...[/dim]"),
        )
    out = output or default_export_path(label, fmt)
    try:
        count = export_to_file(messages, out, fmt, title=label)
    except (OSError, ValueError) as exc:
        fail(str(exc))
    console.print(f"[green]Exported[/green] {count} messages -> {out}")


def default_export_path(label: str, fmt: str) -> str:
    """File name from a label: non-alphanumerics become ``-`` (runs are kept), lower-cased.

    ``"cú đêm #general"`` -> ``"cú-đêm--general.md"``. Kept as-is for compatibility
    with files exported by earlier versions.
    """
    slug = "".join(ch if ch.isalnum() else "-" for ch in label).strip("-").lower() or "export"
    ext = EXPORT_EXTENSIONS.get(fmt.lower(), "md")
    return f"{slug}.{ext}"
