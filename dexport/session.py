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
