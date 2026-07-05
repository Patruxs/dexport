"""Tests for :mod:`dexport.messages` — history paging and request builders.

``fetch_history`` is exercised against ``conftest.FakeApi`` so every request
path it issues is recorded; the builders are pure and checked directly.
"""

import pytest
from conftest import FakeApi

from dexport.errors import ApiError
from dexport.messages import (
    MAX_PAGE_SIZE,
    add_reaction_request,
    delete_message_request,
    edit_message_request,
    encode_emoji,
    fetch_history,
    history_request,
    remove_reaction_request,
    send_message_request,
)

# --------------------------------------------------------------------------
# encode_emoji
# --------------------------------------------------------------------------


def test_encode_unicode_emoji():
    assert encode_emoji("👍") == "%F0%9F%91%8D"


def test_encode_custom_emoji_angle():
    assert encode_emoji("<:blobcat:12345>") == "blobcat%3A12345"
    assert encode_emoji("<a:party:67890>") == "party%3A67890"


def test_encode_custom_emoji_bare():
    assert encode_emoji("blobcat:12345") == "blobcat%3A12345"


def test_encode_strips_whitespace():
    assert encode_emoji("  👍  ") == "%F0%9F%91%8D"


# --------------------------------------------------------------------------
# fetch_history
# --------------------------------------------------------------------------


def _page(newest_id: int, count: int) -> list[dict]:
    """``count`` messages with descending ids from ``newest_id`` (Discord order)."""
    return [{"id": str(newest_id - i), "content": f"m{newest_id - i}"} for i in range(count)]


def _paths(api: FakeApi) -> list[str]:
    return [path for _method, path, _body in api.calls]


def test_fetch_history_pages_until_limit_reached():
    api = (
        FakeApi().queue(200, _page(300, 100)).queue(200, _page(200, 100)).queue(200, _page(100, 50))
    )

    got = fetch_history(api, "c", limit=250)

    assert _paths(api) == [
        "/channels/c/messages?limit=100",
        "/channels/c/messages?limit=100&before=201",
        "/channels/c/messages?limit=50&before=101",
    ]
    assert all(method == "GET" and body is None for method, _path, body in api.calls)
    assert len(got) == 250
    # Newest first, pages concatenated in order.
    assert [m["id"] for m in got] == [str(i) for i in range(300, 50, -1)]


def test_fetch_history_short_page_stops_early():
    api = FakeApi().queue(200, _page(30, 30))
    got = fetch_history(api, "c", limit=250)
    assert [m["id"] for m in got] == [str(i) for i in range(30, 0, -1)]
    assert len(api.calls) == 1


def test_fetch_history_empty_channel_returns_empty_list():
    api = FakeApi().queue(200, [])
    assert fetch_history(api, "c", limit=250) == []
    assert _paths(api) == ["/channels/c/messages?limit=100"]


def test_fetch_history_treats_empty_body_as_no_messages():
    api = FakeApi().queue(200)  # empty body -> ApiResponse.json() is None
    assert fetch_history(api, "c") == []
    assert len(api.calls) == 1


def test_fetch_history_reports_running_totals():
    api = (
        FakeApi().queue(200, _page(300, 100)).queue(200, _page(200, 100)).queue(200, _page(100, 50))
    )
    totals: list[int] = []
    fetch_history(api, "c", limit=250, on_page=totals.append)
    assert totals == [100, 200, 250]
