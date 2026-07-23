"""Write verbs: send / reply / react / edit / delete.

Each verb is ~10 lines: build a request via :mod:`dexport.messages` and hand
it to :func:`~dexport.cli.common.run_write`, which does the dry-run /
confirm / pause / execute dance identically for all of them. To add a verb,
add a request builder in ``messages.py`` and a function like the ones below.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..messages import (
    add_reaction_request,
    delete_message_request,
    edit_message_request,
    send_message_request,
)
from .common import (
    ChannelIdOpt,
    ChannelOpt,
    DryRunOpt,
    GuildIdOpt,
    GuildOpt,
    Target,
    YesOpt,
    run_write,
)

commands = typer.Typer()

MessageOpt = Annotated[str, typer.Option("-m", "--message", help="Message content.")]


@commands.command()
def send(
    ctx: typer.Context,
    message: MessageOpt,
    guild: GuildOpt = None,
    channel: ChannelOpt = None,
    guild_id: GuildIdOpt = None,
    channel_id: ChannelIdOpt = None,
    yes: YesOpt = False,
    dry_run: DryRunOpt = False,
) -> None:
    """Send a message to a channel."""
    run_write(
        ctx,
        Target(guild, channel, guild_id, channel_id),
        build=lambda cid: send_message_request(cid, message),
        confirm="Send message",
        done=lambda r, label: f"[green]Sent[/green] message {r.get('id')} to {label}",
        yes=yes,
        dry_run=dry_run,
    )


@commands.command()
def reply(
    ctx: typer.Context,
    to: Annotated[str, typer.Option("--to", help="Message ID to reply to.")],
    message: MessageOpt,
    guild: GuildOpt = None,
    channel: ChannelOpt = None,
    guild_id: GuildIdOpt = None,
    channel_id: ChannelIdOpt = None,
    yes: YesOpt = False,
    dry_run: DryRunOpt = False,
) -> None:
    """Reply to a specific message."""
    run_write(
        ctx,
        Target(guild, channel, guild_id, channel_id),
        build=lambda cid: send_message_request(cid, message, reply_to=to),
        confirm=f"Reply to {to}",
        done=lambda r, label: f"[green]Replied[/green] with message {r.get('id')} in {label}",
        yes=yes,
        dry_run=dry_run,
    )


@commands.command()
def react(
    ctx: typer.Context,
    to: Annotated[str, typer.Option("--to", help="Message ID to react to.")],
    emoji: Annotated[
        str, typer.Option("-e", "--emoji", help="Unicode emoji or name:id / <:name:id>.")
    ],
    guild: GuildOpt = None,
    channel: ChannelOpt = None,
    guild_id: GuildIdOpt = None,
    channel_id: ChannelIdOpt = None,
    yes: YesOpt = False,
    dry_run: DryRunOpt = False,
) -> None:
    """Add a reaction to a message."""
    run_write(
        ctx,
        Target(guild, channel, guild_id, channel_id),
        build=lambda cid: add_reaction_request(cid, to, emoji),
        confirm=f"React {emoji} to {to}",
        done=lambda _r, label: f"[green]Reacted[/green] {emoji} to {to} in {label}",
        yes=yes,
        dry_run=dry_run,
    )


@commands.command()
def edit(
    ctx: typer.Context,
    to: Annotated[str, typer.Option("--to", help="Message ID to edit (must be yours).")],
    message: MessageOpt,
    guild: GuildOpt = None,
    channel: ChannelOpt = None,
    guild_id: GuildIdOpt = None,
    channel_id: ChannelIdOpt = None,
    yes: YesOpt = False,
    dry_run: DryRunOpt = False,
) -> None:
    """Edit one of your own messages."""
    run_write(
        ctx,
        Target(guild, channel, guild_id, channel_id),
        build=lambda cid: edit_message_request(cid, to, message),
        confirm=f"Edit message {to}",
        done=lambda _r, label: f"[green]Edited[/green] message {to} in {label}",
        yes=yes,
        dry_run=dry_run,
    )


@commands.command()
def delete(
    ctx: typer.Context,
    to: Annotated[str, typer.Option("--to", help="Message ID to delete.")],
    guild: GuildOpt = None,
    channel: ChannelOpt = None,
    guild_id: GuildIdOpt = None,
    channel_id: ChannelIdOpt = None,
    yes: YesOpt = False,
    dry_run: DryRunOpt = False,
) -> None:
    """Delete a message (yours, or any if you have permission)."""
    run_write(
        ctx,
        Target(guild, channel, guild_id, channel_id),
        build=lambda cid: delete_message_request(cid, to),
        confirm=f"Delete message {to}",
        done=lambda _r, label: f"[green]Deleted[/green] message {to} in {label}",
        yes=yes,
        dry_run=dry_run,
    )
