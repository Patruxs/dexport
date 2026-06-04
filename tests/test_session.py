"""Session layer: page selection (pure) and the Playwright-facing primitives.

Everything here runs against small fakes of the Playwright ``Page`` /
``Browser`` / ``Playwright`` objects; no browser or Discord is ever touched.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from dexport.errors import SessionError
from dexport.session import Session, is_discord_url, pick_app_page, score_page

# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class _Page:
    """A page whose only interesting attribute is its URL."""

    def __init__(self, url: str) -> None:
        self.url = url


class _ClosingPage:
    """A page that is going away: reading ``.url`` raises."""

    @property
    def url(self) -> str:
        raise RuntimeError("Target page, context or browser has been closed")


class FakeTimeout(Exception):
    """Stands in for playwright's TimeoutError."""


class FakeRequest:
    def __init__(
        self,
        url: str,
        headers: dict[str, str],
        all_headers: dict[str, str] | None = None,
        *,
        all_headers_fails: bool = False,
    ) -> None:
        self.url = url
        self.headers = headers
        self._all_headers = headers if all_headers is None else all_headers
        self._all_headers_fails = all_headers_fails

    def all_headers(self) -> dict[str, str]:
        if self._all_headers_fails:
            raise RuntimeError("request context gone")
        return dict(self._all_headers)


class _RequestInfo:
    """Like playwright's EventContextManager result: ``.value`` resolves or times out."""

    def __init__(self, page: FakePage, predicate: Any) -> None:
        self._page = page
        self._predicate = predicate

    @property
    def value(self) -> FakeRequest:
        for req in self._page.requests:
            if self._predicate(req):
                return req
        raise FakeTimeout('Timeout exceeded while waiting for event "request"')


class FakePage:
    """Records evaluate/expect_request/reload calls; ``requests`` is what 'fires'."""

    def __init__(
        self,
        *,
        requests: list[FakeRequest] | None = None,
        evaluate_result: Any = None,
        evaluate_error: Exception | None = None,
        reload_error: Exception | None = None,
        expect_request_error: Exception | None = None,
    ) -> None:
        self.requests = list(requests or [])
        self._evaluate_result = evaluate_result
        self._evaluate_error = evaluate_error
        self._reload_error = reload_error
        self._expect_request_error = expect_request_error
        self.evaluate_calls: list[tuple[str, Any]] = []
        self.expect_calls: list[dict[str, Any]] = []
        self.reload_calls: list[dict[str, Any]] = []
        self.events: list[str] = []

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        self.evaluate_calls.append((expression, arg))
        if self._evaluate_error is not None:
            raise self._evaluate_error
        return self._evaluate_result

    @contextmanager
    def expect_request(self, predicate: Any, timeout: float):
        if self._expect_request_error is not None:
            raise self._expect_request_error
        self.expect_calls.append({"predicate": predicate, "timeout": timeout})
        self.events.append("listen:start")
        yield _RequestInfo(self, predicate)
        self.events.append("listen:end")

    def reload(self, **kwargs: Any) -> None:
        self.reload_calls.append(kwargs)
        self.events.append("reload")
        if self._reload_error is not None:
            raise self._reload_error


class FakeBrowser:
    def __init__(self, *, fail: bool = False, pages: list[Any] | None = None) -> None:
        self._fail = fail
        self.closed = False
        self.contexts = [_Context(pages or [])]

    def close(self) -> None:
        self.closed = True
        if self._fail:
            raise RuntimeError("browser already gone")


class _Context:
    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages


class FakePlaywright:
    def __init__(self, *, fail: bool = False, browser: Any = None, connect_error=None) -> None:
        self._fail = fail
        self.stopped = False
        self.chromium = _Chromium(browser, connect_error, self)

    def stop(self) -> None:
        self.stopped = True
        if self._fail:
            raise RuntimeError("driver already stopped")


class _Chromium:
    def __init__(self, browser: Any, connect_error: Exception | None, pw: FakePlaywright) -> None:
        self._browser = browser
        self._connect_error = connect_error
        self._pw = pw
        self.connect_calls: list[str] = []

    def connect_over_cdp(self, endpoint: str) -> Any:
        self.connect_calls.append(endpoint)
        if self._connect_error is not None:
            raise self._connect_error
        return self._browser


def _api_request(url: str = "https://discord.com/api/v9/users/@me") -> FakeRequest:
    return FakeRequest(url, {"authorization": "tok", "x-super-properties": "abc"})


def _any_request(url: str, headers: dict[str, str]) -> bool:
    return True


# --------------------------------------------------------------------------
# is_discord_url / score_page / pick_app_page
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://discord.com/channels/1/2", True),
        ("https://ptb.discord.com/app", True),
        ("https://canary.discord.com", True),
        ("https://discordapp.com", True),
        ("http://discord.com/app", True),
        ("HTTPS://DISCORD.COM/channels/@me", True),
        ("chrome://x", False),
        ("about:blank", False),
        ("", False),
        ("discord.com", False),
        ("devtools://devtools/bundled/inspector.html", False),
        ("https://example.com/", False),
    ],
)
def test_is_discord_url(url, expected):
    assert is_discord_url(url) is expected


def test_score_page_prefers_channels_over_app_over_root_over_overlay():
    channels = score_page("https://discord.com/channels/1/2")
    app = score_page("https://discord.com/app")
    root = score_page("https://discord.com/")
    overlay = score_page("https://discord.com/overlay")
    assert channels > app > root > overlay


@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com/overlay",
        "https://discord.com/splash",
        "https://discord.com/app?notification=1",
    ],
)
def test_score_page_penalises_non_app_renderers_below_root(url):
    assert score_page(url) < score_page("https://discord.com/")
