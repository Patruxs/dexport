"""Lightweight shapes for the Discord objects dexport touches.

Discord's JSON is passed around as plain dicts (``Message`` etc. are aliases,
not classes) so nothing here constrains what the API may return. The
``TypedDict``s describe what dexport itself *stores* in the resolver cache.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, TypedDict

#: A raw Discord message object as returned by the API.
Message = dict[str, Any]


class ChannelType(IntEnum):
    """Subset of Discord channel types dexport needs to tell apart."""

    GUILD_TEXT = 0
    DM = 1
    GUILD_VOICE = 2
    GROUP_DM = 3
    GUILD_CATEGORY = 4
    GUILD_ANNOUNCEMENT = 5
    ANNOUNCEMENT_THREAD = 10
    PUBLIC_THREAD = 11
    PRIVATE_THREAD = 12
    GUILD_STAGE_VOICE = 13
    GUILD_FORUM = 15
    GUILD_MEDIA = 16


#: Channel types you can GET/POST messages on. Forum (15) and media (16) are
#: thread *containers* — messages live in their threads — so they are excluded.
MESSAGE_CHANNEL_TYPES: frozenset[int] = frozenset(
    {
        ChannelType.GUILD_TEXT,
        ChannelType.DM,
        ChannelType.GROUP_DM,
        ChannelType.GUILD_ANNOUNCEMENT,
        ChannelType.ANNOUNCEMENT_THREAD,
        ChannelType.PUBLIC_THREAD,
        ChannelType.PRIVATE_THREAD,
    }
)


class GuildRef(TypedDict):
    """What the resolver caches per guild."""

    id: str
    name: str


class ChannelRef(TypedDict):
    """What the resolver caches per channel."""

    id: str
    name: str
    type: int | None
    parent_id: str | None
