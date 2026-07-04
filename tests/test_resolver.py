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


def test_full_name_beats_short_substring():
    # Regression: 'general chat' must resolve to 'general-chat', not 'gen'.
    cache = {
        "guilds": [{"id": "1", "name": "srv"}],
        "channels": {
            "1": [
                {"id": "111", "name": "gen", "type": 0},
                {"id": "222", "name": "general-chat", "type": 0},
            ]
        },
    }
    assert Resolver(NoApi(), cache).resolve_channel("1", "general chat")["id"] == "222"


def test_forum_channel_not_matched_for_messaging():
    cache = {
        "guilds": [{"id": "1", "name": "srv"}],
        "channels": {"1": [{"id": "500", "name": "help", "type": 15}]},
    }
    with pytest.raises(ResolveError):
        Resolver(NoApi(), cache).resolve_channel("1", "help")


def test_numeric_channel_name_resolves_by_name():
    # A 16-digit channel name is not a snowflake, so it matches by name.
    cache = {
        "guilds": [{"id": "1", "name": "srv"}],
        "channels": {"1": [{"id": "999", "name": "1234567890123456", "type": 0}]},
    }
    assert Resolver(NoApi(), cache).resolve_channel("1", "1234567890123456")["id"] == "999"
