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


def test_resolve_guild_by_cached_id_returns_cached_entry(resolver):
    # An ID already in the cache must return the real name, not a passthrough.
    assert resolver.resolve_guild("1") == {"id": "1", "name": "cú đêm"}


def test_resolve_channel_by_id_bypasses_type_filter(resolver):
    # An explicit channel ID is trusted even for a voice channel.
    assert resolver.resolve_channel("1", "11")["name"] == "voice-hangout"


# --------------------------------------------------------------------------
# Snowflake passthrough shapes
# --------------------------------------------------------------------------


def test_resolve_guild_passthrough_entry_has_id_and_name(resolver):
    assert resolver.resolve_guild(SNOWFLAKE) == {"id": SNOWFLAKE, "name": SNOWFLAKE}


def test_resolve_channel_passthrough_entry_has_all_four_keys(resolver):
    assert resolver.resolve_channel("1", SNOWFLAKE) == {
        "id": SNOWFLAKE,
        "name": SNOWFLAKE,
        "type": None,
        "parent_id": None,
    }


def test_resolve_channel_non_snowflake_number_is_not_passed_through(resolver):
    with pytest.raises(ResolveError):
        resolver.resolve_channel("1", "12345")


# --------------------------------------------------------------------------
# Cache population through the API
# --------------------------------------------------------------------------


def test_guilds_first_call_fetches_and_stores_only_id_and_name():
    api = FakeApi().queue(
        200,
        [
            {"id": "1", "name": "srv", "icon": "abc", "owner": True, "permissions": "0"},
            {"id": "2", "name": "other", "features": ["COMMUNITY"]},
        ],
    )
    r = Resolver(api, {})

    got = r.guilds()

    assert api.calls == [("GET", "/users/@me/guilds", None)]
    assert got == [{"id": "1", "name": "srv"}, {"id": "2", "name": "other"}]
    assert r.cache["guilds"] == got


def test_guilds_second_call_does_not_fetch():
    api = FakeApi().queue(200, [{"id": "1", "name": "srv"}])
    r = Resolver(api, {})

    first = r.guilds()
    second = r.guilds()

    assert second == first
    assert len(api.calls) == 1


def test_guilds_refresh_refetches_and_replaces_cache():
    api = (
        FakeApi().queue(200, [{"id": "1", "name": "old"}]).queue(200, [{"id": "1", "name": "new"}])
    )
    r = Resolver(api, {})
    r.guilds()

    got = r.guilds(refresh=True)

    assert got == [{"id": "1", "name": "new"}]
    assert r.cache["guilds"] == got
    assert len(api.calls) == 2


def test_zero_guilds_caches_empty_list_and_does_not_refetch():
    # Regression: the "already fetched" check must be ``is None``, not falsy,
    # or an account in no guilds would hit the API on every call.
    api = FakeApi().queue(200, [])
    r = Resolver(api, {})

    assert r.guilds() == []
    assert r.cache["guilds"] == []
    assert r.guilds() == []  # FakeApi would raise on a second request
    assert len(api.calls) == 1


def test_channels_fetches_and_stores_four_keys_keyed_by_guild():
    api = FakeApi().queue(
        200,
        [
            {
                "id": "10",
                "name": "general",
                "type": 0,
                "parent_id": "9",
                "position": 3,
                "topic": "chatter",
                "nsfw": False,
            }
        ],
    )
    r = Resolver(api, {})

    got = r.channels("1")

    assert api.calls == [("GET", "/guilds/1/channels", None)]
    assert got == [{"id": "10", "name": "general", "type": 0, "parent_id": "9"}]
    assert r.cache["channels"] == {"1": got}


def test_channels_missing_optional_fields_default_to_empty_or_none():
    api = FakeApi().queue(200, [{"id": "10"}])
    got = Resolver(api, {}).channels("1")
    assert got == [{"id": "10", "name": "", "type": None, "parent_id": None}]


def test_channels_second_call_does_not_fetch():
    api = FakeApi().queue(200, [{"id": "10", "name": "general", "type": 0}])
    r = Resolver(api, {})

    first = r.channels("1")
    second = r.channels("1")

    assert second == first
    assert len(api.calls) == 1


def test_channels_are_cached_per_guild():
    api = (
        FakeApi()
        .queue(200, [{"id": "10", "name": "a", "type": 0}])
        .queue(200, [{"id": "20", "name": "b", "type": 0}])
    )
    r = Resolver(api, {})

    r.channels("1")
    r.channels("2")
    r.channels("1")

    assert [path for _, path, _ in api.calls] == ["/guilds/1/channels", "/guilds/2/channels"]
    assert set(r.cache["channels"]) == {"1", "2"}
    assert r.cache["channels"]["2"] == [{"id": "20", "name": "b", "type": 0, "parent_id": None}]


def test_channels_refresh_refetches():
    api = (
        FakeApi()
        .queue(200, [{"id": "10", "name": "old", "type": 0}])
        .queue(200, [{"id": "10", "name": "new", "type": 0}])
    )
    r = Resolver(api, {})
    r.channels("1")

    assert r.channels("1", refresh=True)[0]["name"] == "new"
    assert len(api.calls) == 2


def test_resolve_guild_fetches_when_cache_empty():
    api = FakeApi().queue(200, [{"id": "1", "name": "my server"}])
    got = Resolver(api, {}).resolve_guild("my server")
    assert got == {"id": "1", "name": "my server"}
    assert api.calls == [("GET", "/users/@me/guilds", None)]


def test_resolve_channel_fetches_when_guild_not_cached():
    api = FakeApi().queue(200, [{"id": "10", "name": "general", "type": 0}])
    got = Resolver(api, {}).resolve_channel("7", "general")
    assert got["id"] == "10"
    assert api.calls == [("GET", "/guilds/7/channels", None)]


def test_resolver_mutates_caller_cache_in_place():
    # The owner persists ``resolver.cache`` on exit, so it must be the same dict.
    api = FakeApi().queue(200, [{"id": "1", "name": "srv"}])
    cache = {}
    r = Resolver(api, cache)

    r.guilds()

    assert r.cache is cache
    assert cache["guilds"] == [{"id": "1", "name": "srv"}]


# --------------------------------------------------------------------------
# Cache shape helpers
# --------------------------------------------------------------------------


def test_empty_cache_shape():
    assert empty_cache() == {"guilds": None, "channels": {}}
