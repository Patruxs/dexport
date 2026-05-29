"""Tests for :mod:`dexport.errors` — the exception hierarchy and message helpers."""

import pytest

from dexport.errors import (
    ApiError,
    DexportError,
    HeaderCaptureError,
    LauncherError,
    RateLimitError,
    ResolveError,
    SessionError,
    extract_message,
)

ALL_ERRORS = [
    LauncherError,
    SessionError,
    HeaderCaptureError,
    ApiError,
    RateLimitError,
    ResolveError,
]


# --------------------------------------------------------------------------
# extract_message
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"message": "Missing Access", "code": 50001}, "Missing Access"),
        ({"code": 50001}, None),
        ({"message": 42}, None),
        ({"message": None}, None),
        ("Missing Access", None),
        (["message"], None),
        (None, None),
    ],
)
def test_extract_message(body, expected):
    assert extract_message(body) == expected


# --------------------------------------------------------------------------
# ApiError
# --------------------------------------------------------------------------


def test_api_error_message_includes_discord_detail():
    err = ApiError(403, {"message": "Missing Access", "code": 50001})
    assert str(err) == "Discord API returned 403: Missing Access"
    assert err.status == 403
    assert err.body == {"message": "Missing Access", "code": 50001}


@pytest.mark.parametrize("body", [None, "boom", {"code": 0}, ["x"]])
def test_api_error_message_without_detail(body):
    err = ApiError(500, body)
    assert str(err) == "Discord API returned 500"
    assert err.body == body
