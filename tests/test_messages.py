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
