import copy

import pytest
from conftest import FakeApi

from dexport.errors import ResolveError
from dexport.resolver import DEFAULT_THRESHOLD, Resolver, empty_cache, normalize_cache, score


class NoApi:
    def get_json(self, path):  # pragma: no cover - must not be called
        raise AssertionError(f"unexpected fetch: {path}")


@pytest.fixture
def resolver(resolver_cache):
    return Resolver(NoApi(), resolver_cache)


SNOWFLAKE = "999999999999999999"


# --------------------------------------------------------------------------
# Resolving against a pre-populated cache (no API calls)
# --------------------------------------------------------------------------


def test_resolve_guild_diacritics_insensitive(resolver):
    assert resolver.resolve_guild("cu dem")["id"] == "1"


def test_resolve_channel_diacritics_insensitive(resolver):
    assert resolver.resolve_channel("1", "luoi chat tong")["id"] == "10"


def test_resolve_channel_accepts_hash_prefix(resolver):
    assert resolver.resolve_channel("1", "#thong bao")["id"] == "12"


def test_resolve_channel_skips_non_text(resolver):
    # A voice channel should not be matched for text operations.
    with pytest.raises(ResolveError):
        resolver.resolve_channel("1", "voice-hangout", threshold=99)
