"""Resolve human names to Discord IDs, with a small on-disk cache.

Guild and channel lists are fetched once and cached under ~/.dexport/cache.json.
Matching is diacritics-insensitive (so ``"cu dem"`` finds ``"cú đêm"``) and
falls back to fuzzy scoring for near-misses.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from rapidfuzz import fuzz

from .errors import ResolveError
from .models import MESSAGE_CHANNEL_TYPES, ChannelRef, GuildRef
from .util import is_snowflake, normalize

#: Minimum 0..100 similarity for a fuzzy match to be accepted.
DEFAULT_THRESHOLD = 60.0

#: Shape of ``cache.json``: ``{"guilds": list | None, "channels": {guild_id: list}}``.
#: ``guilds`` is ``None`` until first fetched.
ResolverCache = dict[str, Any]

_Ref = TypeVar("_Ref", GuildRef, ChannelRef)


class JsonGetter(Protocol):
    """What :class:`Resolver` needs from the API layer."""

    def get_json(self, path: str) -> Any: ...


def empty_cache() -> ResolverCache:
    return {"guilds": None, "channels": {}}


def normalize_cache(cache: ResolverCache) -> ResolverCache:
    """Repair a loaded cache **in place** so every key has the right type."""
    if not isinstance(cache.get("guilds"), list):
        cache["guilds"] = None
    if not isinstance(cache.get("channels"), dict):
        cache["channels"] = {}
    return cache
