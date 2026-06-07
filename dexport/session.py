"""CDP attach layer built on Playwright — the *only* module that touches it.

We connect to Discord's own Electron renderer over CDP (we never launch our own
browser), locate the page that is actually the Discord app, and expose the two
primitives the rest of the tool needs:

* :meth:`Session.evaluate` — run JS in the page (this is how in-page ``fetch``
  works; see :mod:`dexport.api`).
* :meth:`Session.wait_for_request` — observe an outgoing request's headers
  (this is how the header snapshot works; see :mod:`dexport.headers`).

Both are small enough to fake in tests, which is why nothing else in the
package imports Playwright.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Protocol, Self

from .errors import SessionError

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page, Playwright

# discord.com covers stable; the others cover PTB/Canary and the legacy host.
DISCORD_HOSTS = ("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com")

# Overlay, splash, notifications and the like are separate renderers.
_NON_APP_MARKERS = ("overlay", "splash", "notification", "devtools://", "about:blank")

#: ``(url, lower-cased request headers) -> bool``
RequestPredicate = Callable[[str, dict[str, str]], bool]


class Evaluator(Protocol):
    """What :class:`~dexport.api.ApiCore` needs from a session."""

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...


# --------------------------------------------------------------------------
# Page selection (pure — unit-tested without Playwright)
# --------------------------------------------------------------------------


def is_discord_url(url: str) -> bool:
    if not url:
        return False
    lowered = url.lower()
    if not lowered.startswith(("http://", "https://")):
        return False
    return any(host in lowered for host in DISCORD_HOSTS)


def score_page(url: str) -> int:
    """Higher is better. Prefer the real app view over splash/overlay/settings."""
    lowered = url.lower()
    score = 0
    if "/channels" in lowered:
        score += 100
    if "/app" in lowered:
        score += 50
    for bad in _NON_APP_MARKERS:
        if bad in lowered:
            score -= 100
    return score


def pick_app_page(pages: Iterable[Any]) -> Any | None:
    """The page (object with a ``.url`` attribute) most likely to be the app."""
    best = None
    best_score = -(10**9)
    for page in pages:
        try:
            url = page.url
        except Exception:  # noqa: BLE001, S112 - page may be closing; skip it
            continue
        if not is_discord_url(url):
            continue
        score = score_page(url)
        if score > best_score:
            best_score = score
            best = page
    return best


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


class Session:
    """A live CDP attachment to the Discord client's app page."""

    def __init__(self, playwright: Playwright, browser: Browser, page: Page) -> None:
        self._pw = playwright
        self._browser = browser
        self._page = page

    # -- construction -------------------------------------------------------
    @classmethod
    def connect(cls, cdp_http_url: str) -> Self:
        # Imported lazily: Playwright is heavy and only this path needs it.
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - env dependent
            raise SessionError("Playwright is not installed. Run: pip install playwright") from exc

        pw = sync_playwright().start()
        try:
            browser = pw.chromium.connect_over_cdp(cdp_http_url)
        except Exception as exc:
            pw.stop()
            raise SessionError(
                f"Could not attach to Discord over CDP at {cdp_http_url}: {exc}"
            ) from exc

        page = pick_app_page(p for ctx in browser.contexts for p in ctx.pages)
        if page is None:
            browser.close()
            pw.stop()
            raise SessionError(
                "Attached to Discord but found no app page (looked for a "
                "discord.com renderer). Is a channel/DM open in the client?"
            )
        return cls(pw, browser, page)

    # -- primitives ---------------------------------------------------------
    def evaluate(self, expression: str, arg: Any = None) -> Any:
        """Run ``expression`` (a JS function or expression) in the page."""
        try:
            return self._page.evaluate(expression, arg)
        except Exception as exc:
            raise SessionError(f"In-page evaluate failed: {exc}") from exc

    def wait_for_request(
        self,
        predicate: RequestPredicate,
        *,
        timeout: float,
        reload: bool = False,
        reload_timeout: float = 30.0,
    ) -> dict[str, str] | None:
        """Block until an outgoing request satisfies ``predicate``.

        Returns that request's headers (lower-cased names), or ``None`` if
        nothing matched within ``timeout`` seconds. With ``reload`` the page is
        reloaded *while* listening — Discord fires a burst of API requests on
        load, which is the reliable way to provoke one.
        """
        try:
            with self._page.expect_request(
                lambda req: predicate(req.url, req.headers),
                timeout=timeout * 1000,
            ) as info:
                if reload:
                    # Blocking (sync Playwright), but the listener above is
                    # already armed, so the request we want is not missed. A
                    # reload error (navigation race) is fine: the listener's
                    # own timeout decides the outcome.
                    with suppress(Exception):
                        self._page.reload(timeout=int(reload_timeout * 1000), wait_until="commit")
            request = info.value
        except Exception:  # noqa: BLE001 - timeout / navigation
            return None

        try:
            raw = request.all_headers()
        except Exception:  # noqa: BLE001
            raw = dict(request.headers)
        return {k.lower(): v for k, v in raw.items()}

    # -- teardown -----------------------------------------------------------
    def close(self) -> None:
        # Closing a connect_over_cdp browser only detaches CDP; it does not
        # close Discord itself. Best effort: Discord may already be gone.
        with suppress(Exception):
            self._browser.close()
        with suppress(Exception):
            self._pw.stop()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
