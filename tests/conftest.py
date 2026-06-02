"""Shared fixtures. Nothing here needs a running Discord client.

* ``dexport_home`` (autouse) — points ``DEXPORT_HOME`` at a temp dir so no
  test can ever read or write the developer's real ``~/.dexport``.
* ``FakeSession`` / ``fake_session`` — a stand-in for the CDP session that
  returns queued fetch results (see :func:`resp`).
* ``no_sleep_limiter`` — a :class:`RateLimiter` that never sleeps.
* ``FakeApi`` — records every request and returns queued responses; use it
  where code takes an ``ApiCore``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dexport.api import ApiRequest, ApiResponse
from dexport.ratelimit import RateLimiter

# --------------------------------------------------------------------------
# Isolation
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def dexport_home(tmp_path, monkeypatch):
    """Every test gets its own ``$DEXPORT_HOME``; returns the directory."""
    home = tmp_path / "dexport-home"
    monkeypatch.setenv("DEXPORT_HOME", str(home))
    monkeypatch.delenv("DEXPORT_PORT", raising=False)
    monkeypatch.delenv("DEXPORT_DISCORD_BINARY", raising=False)
    return home


# --------------------------------------------------------------------------
# Session / fetch fakes (for ApiCore)
# --------------------------------------------------------------------------


def resp(status: int, body: str = "", headers: dict[str, str] | None = None, error=None) -> dict:
    """Build a raw fetch result exactly as ``_FETCH_JS`` would return it."""
    return {"status": status, "body": body, "headers": headers or {}, "error": error}
