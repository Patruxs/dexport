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


def test_pick_app_page_returns_highest_scoring_discord_page():
    app = _Page("https://discord.com/app")
    channels = _Page("https://discord.com/channels/1/2")
    overlay = _Page("https://discord.com/overlay")
    other = _Page("chrome://gpu")
    assert pick_app_page([app, overlay, channels, other]) is channels


def test_pick_app_page_ignores_non_discord_pages_even_if_they_look_like_the_app():
    decoy = _Page("https://example.com/channels/1/2")
    real = _Page("https://discord.com/app")
    assert pick_app_page([decoy, real]) is real


def test_pick_app_page_skips_pages_whose_url_raises():
    real = _Page("https://discord.com/app")
    assert pick_app_page([_ClosingPage(), real, _ClosingPage()]) is real


def test_pick_app_page_falls_back_to_a_low_scoring_discord_page():
    # Only an overlay renderer is open: better to attach to it than to nothing.
    overlay = _Page("https://discord.com/overlay")
    assert pick_app_page([_Page("about:blank"), overlay]) is overlay


def test_pick_app_page_prefers_first_of_equal_scores():
    first = _Page("https://discord.com/channels/1/2")
    second = _Page("https://discord.com/channels/3/4")
    assert pick_app_page([first, second]) is first


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [_Page("chrome://x"), _Page("about:blank")],
        [_ClosingPage()],
    ],
)
def test_pick_app_page_returns_none_when_no_discord_page(pages):
    assert pick_app_page(pages) is None


def test_pick_app_page_accepts_any_iterable():
    real = _Page("https://discord.com/channels/@me")
    assert pick_app_page(p for p in [_Page("about:blank"), real]) is real


# --------------------------------------------------------------------------
# Session.evaluate
# --------------------------------------------------------------------------


def test_evaluate_forwards_expression_and_arg_and_returns_result():
    page = FakePage(evaluate_result={"status": 200})
    session = Session(None, None, page)
    out = session.evaluate("async (x) => x", {"a": 1})
    assert out == {"status": 200}
    assert page.evaluate_calls == [("async (x) => x", {"a": 1})]


def test_evaluate_defaults_arg_to_none():
    page = FakePage(evaluate_result=42)
    assert Session(None, None, page).evaluate("1 + 41") == 42
    assert page.evaluate_calls == [("1 + 41", None)]


def test_evaluate_wraps_page_errors_in_session_error():
    page = FakePage(evaluate_error=RuntimeError("Execution context was destroyed"))
    with pytest.raises(SessionError, match="Execution context was destroyed") as exc:
        Session(None, None, page).evaluate("1")
    assert isinstance(exc.value.__cause__, RuntimeError)


# --------------------------------------------------------------------------
# Session.wait_for_request
# --------------------------------------------------------------------------


def test_wait_for_request_returns_lowercased_headers_of_matching_request():
    req = FakeRequest(
        "https://discord.com/api/v9/users/@me",
        {"authorization": "tok"},
        all_headers={"Authorization": "tok", "X-Super-Properties": "abc"},
    )
    page = FakePage(requests=[req])
    out = Session(None, None, page).wait_for_request(_any_request, timeout=1.0)
    assert out == {"authorization": "tok", "x-super-properties": "abc"}


def test_wait_for_request_passes_url_and_headers_to_predicate():
    seen: list[tuple[str, dict[str, str]]] = []

    def predicate(url: str, headers: dict[str, str]) -> bool:
        seen.append((url, headers))
        return url.endswith("/users/@me")

    asset = FakeRequest("https://discord.com/assets/app.js", {"accept": "*/*"})
    api = _api_request()
    page = FakePage(requests=[asset, api])
    out = Session(None, None, page).wait_for_request(predicate, timeout=1.0)
    assert out == api.headers
    assert seen == [(asset.url, asset.headers), (api.url, api.headers)]


def test_wait_for_request_falls_back_to_headers_when_all_headers_fails():
    req = FakeRequest(
        "https://discord.com/api/v9/users/@me",
        {"Authorization": "tok"},
        all_headers_fails=True,
    )
    page = FakePage(requests=[req])
    out = Session(None, None, page).wait_for_request(_any_request, timeout=1.0)
    assert out == {"authorization": "tok"}


def test_wait_for_request_timeout_is_converted_to_milliseconds():
    page = FakePage(requests=[_api_request()])
    Session(None, None, page).wait_for_request(_any_request, timeout=1.5)
    assert page.expect_calls[0]["timeout"] == 1500


def test_wait_for_request_returns_none_when_nothing_matches():
    page = FakePage(requests=[_api_request()])
    out = Session(None, None, page).wait_for_request(lambda url, headers: False, timeout=0)
    assert out is None


def test_wait_for_request_returns_none_when_listener_itself_raises():
    page = FakePage(expect_request_error=FakeTimeout("Timeout 0ms exceeded"))
    out = Session(None, None, page).wait_for_request(_any_request, timeout=0)
    assert out is None


def test_wait_for_request_does_not_reload_by_default():
    page = FakePage(requests=[_api_request()])
    Session(None, None, page).wait_for_request(_any_request, timeout=1.0)
    assert page.reload_calls == []


def test_wait_for_request_reload_uses_commit_and_millisecond_timeout():
    page = FakePage(requests=[_api_request()])
    Session(None, None, page).wait_for_request(
        _any_request, timeout=1.0, reload=True, reload_timeout=2.5
    )
    assert page.reload_calls == [{"timeout": 2500, "wait_until": "commit"}]


def test_wait_for_request_reload_happens_while_listener_is_armed():
    page = FakePage(requests=[_api_request()])
    Session(None, None, page).wait_for_request(_any_request, timeout=1.0, reload=True)
    assert page.events == ["listen:start", "reload", "listen:end"]
