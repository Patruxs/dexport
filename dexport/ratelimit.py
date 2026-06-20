"""Rate limiter — the safety layer between us and Discord's API.

Design (see docs/ARCHITECTURE.md), from cheapest to most correct:

* A self-imposed **floor delay** (250-600ms + jitter) before every request.
  This is the real protection for a low-volume personal tool.
* Read ``X-RateLimit-Remaining`` / ``X-RateLimit-Reset-After`` after each
  response and, when a route's remaining hits zero, sleep until its reset
  *before* the next call on that route.
* On ``429``, sleep for ``retry_after`` (from the body, header as fallback) and
  retry. A ``X-RateLimit-Global`` / ``global: true`` marks a global limit and
  blocks every route until it clears.

Routes are keyed locally by ``METHOD path-with-ids-masked`` which lines up with
Discord's per-route+major-param buckets closely enough for this use.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

_SNOWFLAKE_RE = re.compile(r"\d{15,}")

#: Self-imposed delay window (seconds) before every request. These are the
#: single source of truth; ``config.Settings`` imports them as its defaults.
DEFAULT_FLOOR_MIN = 0.25
DEFAULT_FLOOR_MAX = 0.6


def route_key(method: str, path: str) -> str:
    """Collapse IDs so calls on the same route share a limiter entry."""
    # Drop any query string; buckets are per path, not per query.
    path = path.split("?", 1)[0]
    masked = _SNOWFLAKE_RE.sub("{id}", path)
    return f"{method.upper()} {masked}"


@dataclass
class _RouteState:
    remaining: int = 1
    reset_at: float = 0.0
