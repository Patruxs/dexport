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


def score(query: str, candidate: str) -> float:
    """0..100 similarity between two names after :func:`normalize`."""
    q, c = normalize(query), normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 100.0
    # WRatio already blends partial matching with length-aware scaling.
    # Do NOT max() it with a raw partial_ratio: that lets a short name that
    # is a substring of the query (e.g. "gen" for "general chat") score 100
    # and outrank the intended full-name match.
    return float(fuzz.WRatio(q, c))


class Resolver:
    """Name → ID lookups backed by :class:`ApiCore` and a dict cache.

    The cache dict is mutated in place so the owner (``Dexport``) can persist
    ``resolver.cache`` on exit without the resolver knowing about disk.
    """

    def __init__(self, api: JsonGetter, cache: ResolverCache | None = None) -> None:
        self.api = api
        self.cache = normalize_cache(cache if cache is not None else empty_cache())

    # -- fetching -----------------------------------------------------------
    def guilds(self, *, refresh: bool = False) -> list[GuildRef]:
        # ``is None`` (not falsy): an account in zero guilds caches ``[]``.
        if refresh or self.cache["guilds"] is None:
            data = self.api.get_json("/users/@me/guilds")
            self.cache["guilds"] = [
                GuildRef(id=g["id"], name=g.get("name", "")) for g in (data or [])
            ]
        guilds: list[GuildRef] = self.cache["guilds"]
        return guilds

    def channels(self, guild_id: str, *, refresh: bool = False) -> list[ChannelRef]:
        store = self.cache["channels"]
        if refresh or guild_id not in store:
            data = self.api.get_json(f"/guilds/{guild_id}/channels")
            store[guild_id] = [
                ChannelRef(
                    id=c["id"],
                    name=c.get("name", ""),
                    type=c.get("type"),
                    parent_id=c.get("parent_id"),
                )
                for c in (data or [])
            ]
        channels: list[ChannelRef] = store[guild_id]
        return channels

    # -- resolving ----------------------------------------------------------
    def resolve_guild(self, query: str, *, threshold: float = DEFAULT_THRESHOLD) -> GuildRef:
        guilds = self.guilds()
        for g in guilds:
            if g["id"] == query:
                return g
        try:
            return _best(query, guilds, "guild", threshold)
        except ResolveError:
            # An ID-shaped query that matched nothing may be a valid but
            # uncached guild ID; fall back to using it verbatim.
            if is_snowflake(query):
                return GuildRef(id=query, name=query)
            raise

    def resolve_channel(
        self, guild_id: str, query: str, *, threshold: float = DEFAULT_THRESHOLD
    ) -> ChannelRef:
        chans = self.channels(guild_id)
        for c in chans:
            if c["id"] == query:
                return c
        # Discord channel names have no leading '#'; tolerate the user typing one.
        q = query.removeprefix("#")
        candidates = [c for c in chans if c.get("type") in MESSAGE_CHANNEL_TYPES]
        try:
            return _best(q, candidates, "channel", threshold)
        except ResolveError:
            if is_snowflake(query):
                return ChannelRef(id=query, name=query, type=None, parent_id=None)
            raise


def _best(query: str, items: list[_Ref], kind: str, threshold: float) -> _Ref:
    """Top-scoring item, or :class:`ResolveError` with the closest names as hints."""
    if not items:
        raise ResolveError(f"No {kind}s available to match {query!r}.")
    ranked = sorted(
        ((score(query, it.get("name", "")), it) for it in items),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best = ranked[0]
    if best_score < threshold:
        hints = ", ".join(repr(it.get("name", "")) for _, it in ranked[:5])
        raise ResolveError(
            f"Could not confidently match {kind} {query!r} "
            f"(best {best_score:.0f}%). Closest: {hints}"
        )
    return best
