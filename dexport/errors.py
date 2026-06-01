"""Exception hierarchy for dexport.

Every failure that is *expected* (a step in the pipeline that can go wrong for
an understandable reason) is raised as a :class:`DexportError` subclass so the
CLI can present a clean message instead of a traceback.
"""

from __future__ import annotations


class DexportError(Exception):
    """Base class for all dexport errors."""


class LauncherError(DexportError):
    """Discord could not be found, launched, or made debuggable."""


class SessionError(DexportError):
    """The CDP session could not be established or the target page was lost."""


class HeaderCaptureError(DexportError):
    """No authorized ``/api/v9`` request was observed to snapshot headers from."""


class ApiError(DexportError):
    """A Discord API call returned a non-success status.

    Attributes
    ----------
    status:
        HTTP status code returned by Discord.
    body:
        Parsed JSON body when available, otherwise the raw text.
    """

    def __init__(self, status: int, body: object, message: str | None = None) -> None:
        self.status = status
        self.body = body
        detail = message or extract_message(body) or ""
        super().__init__(f"Discord API returned {status}{': ' + detail if detail else ''}")


class RateLimitError(DexportError):
    """A request kept hitting rate limits past the retry budget."""


class ResolveError(DexportError):
    """A guild or channel name could not be resolved to an ID."""


def extract_message(body: object) -> str | None:
    """Discord's human-readable ``message`` field from an error body, if any."""
    if isinstance(body, dict):
        msg = body.get("message")
        if isinstance(msg, str):
            return msg
    return None
