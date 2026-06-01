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


def test_api_error_explicit_message_overrides_body():
    err = ApiError(401, {"message": "401: Unauthorized"}, "token rotated")
    assert str(err) == "Discord API returned 401: token rotated"
    assert err.body == {"message": "401: Unauthorized"}  # still available for inspection


def test_api_error_status_zero_for_renderer_failures():
    err = ApiError(0, None, "fetch failed in renderer: TypeError")
    assert str(err) == "Discord API returned 0: fetch failed in renderer: TypeError"
    assert err.status == 0


# --------------------------------------------------------------------------
# Hierarchy
# --------------------------------------------------------------------------


@pytest.mark.parametrize("cls", ALL_ERRORS)
def test_every_error_derives_from_dexport_error(cls):
    assert issubclass(cls, DexportError)


def test_dexport_error_is_an_exception():
    assert issubclass(DexportError, Exception)


@pytest.mark.parametrize(
    "cls", [LauncherError, SessionError, HeaderCaptureError, RateLimitError, ResolveError]
)
def test_simple_errors_carry_their_message(cls):
    with pytest.raises(DexportError, match="something broke"):
        raise cls("something broke")


def test_api_error_caught_as_dexport_error():
    with pytest.raises(DexportError) as exc:
        raise ApiError(404, {"message": "Unknown Channel"})
    assert isinstance(exc.value, ApiError)
    assert exc.value.status == 404


def test_rate_limit_and_api_errors_are_distinct():
    # ApiCore raises one or the other; callers must be able to tell them apart.
    assert not issubclass(RateLimitError, ApiError)
    assert not issubclass(ApiError, RateLimitError)
