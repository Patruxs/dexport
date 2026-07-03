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


def test_fetch_history_on_page_not_called_for_empty_channel():
    api = FakeApi().queue(200, [])
    totals: list[int] = []
    fetch_history(api, "c", on_page=totals.append)
    assert totals == []


def test_fetch_history_before_seed_used_on_first_request():
    api = FakeApi().queue(200, _page(998, 10))
    fetch_history(api, "c", limit=10, before="999")
    assert _paths(api) == ["/channels/c/messages?limit=10&before=999"]


def test_fetch_history_small_limit_requests_exact_page_size():
    api = FakeApi().queue(200, _page(25, 25))
    got = fetch_history(api, "c", limit=25)
    assert _paths(api) == ["/channels/c/messages?limit=25"]
    assert len(got) == 25


def test_fetch_history_stops_at_limit_without_probing_next_page():
    # One full page satisfies limit=100; must not issue a second request.
    api = FakeApi().queue(200, _page(100, 100))
    got = fetch_history(api, "c", limit=100)
    assert len(got) == 100
    assert len(api.calls) == 1


def test_fetch_history_truncates_overfull_page_to_limit():
    api = FakeApi().queue(200, _page(7, 7))
    got = fetch_history(api, "c", limit=5)
    assert [m["id"] for m in got] == ["7", "6", "5", "4", "3"]


def test_fetch_history_default_limit_is_one_page():
    api = FakeApi().queue(200, _page(100, 100))
    assert len(fetch_history(api, "c")) == MAX_PAGE_SIZE
    assert _paths(api) == [f"/channels/c/messages?limit={MAX_PAGE_SIZE}"]


def test_fetch_history_propagates_api_errors():
    api = FakeApi().queue(403, {"message": "Missing Access"})
    with pytest.raises(ApiError, match="Missing Access"):
        fetch_history(api, "c")


# --------------------------------------------------------------------------
# Request builders
# --------------------------------------------------------------------------


def test_send_message_request_plain():
    req = send_message_request("c", "hi")
    assert (req.method, req.path) == ("POST", "/channels/c/messages")
    assert req.body == {"content": "hi"}


def test_send_message_request_reply_defaults_to_lenient_reference():
    req = send_message_request("c", "hi", reply_to="m")
    assert req.body == {
        "content": "hi",
        "message_reference": {"channel_id": "c", "message_id": "m", "fail_if_not_exists": False},
    }


def test_send_message_request_reply_strict_reference():
    req = send_message_request("c", "hi", reply_to="m", fail_if_not_exists=True)
    assert req.body["message_reference"]["fail_if_not_exists"] is True


def test_send_message_request_ignores_fail_flag_without_reply():
    req = send_message_request("c", "hi", fail_if_not_exists=True)
    assert "message_reference" not in req.body
