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
