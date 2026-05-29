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
