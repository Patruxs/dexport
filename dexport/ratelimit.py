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


@dataclass
class RateLimiter:
    floor_min: float = DEFAULT_FLOOR_MIN
    floor_max: float = DEFAULT_FLOOR_MAX
    clock: Callable[[], float] = time.time
    sleeper: Callable[[float], None] = time.sleep
    jitter: Callable[[float, float], float] = random.uniform

    _routes: dict[str, _RouteState] = field(default_factory=dict)
    _global_reset_at: float = 0.0

    # -- pre-flight ---------------------------------------------------------
    def acquire(self, key: str) -> None:
        """Block until it is polite to issue the request identified by ``key``."""
        now = self.clock()
        if now < self._global_reset_at:
            self._sleep_until(self._global_reset_at)

        state = self._routes.get(key)
        if state is not None and state.remaining <= 0:
            now = self.clock()
            if now < state.reset_at:
                self._sleep_until(state.reset_at)

        floor = self.jitter(self.floor_min, self.floor_max)
        if floor > 0:
            self.sleeper(floor)

    # -- post-flight --------------------------------------------------------
    def update(self, key: str, headers: dict[str, str]) -> None:
        """Learn a route's remaining budget from response headers."""
        remaining = headers.get("x-ratelimit-remaining")
        reset_after = headers.get("x-ratelimit-reset-after")
        if remaining is None or reset_after is None:
            return
        try:
            rem = int(float(remaining))
            reset_at = self.clock() + float(reset_after)
        except (TypeError, ValueError):
            return
        self._routes[key] = _RouteState(remaining=rem, reset_at=reset_at)

    def note_429(self, headers: dict[str, str], body: object, key: str | None = None) -> float:
        """Record a 429 and return how many seconds to wait before retrying.

        A global limit blocks every route; otherwise, when ``key`` is given, the
        route itself is penalised so the next :meth:`acquire` on it waits. This
        keeps "record a 429" a single call.
        """
        retry_after = _retry_after_seconds(headers, body)
        if _is_global(headers, body):
            self._global_reset_at = max(self._global_reset_at, self.clock() + retry_after)
        elif key is not None:
            self.penalize(key, retry_after)
        return retry_after

    def penalize(self, key: str, retry_after: float) -> None:
        """After a per-route 429, force the route to wait ``retry_after`` s."""
        self._routes[key] = _RouteState(remaining=0, reset_at=self.clock() + retry_after)

    # -- helpers ------------------------------------------------------------
    def _sleep_until(self, when: float) -> None:
        delay = when - self.clock()
        if delay > 0:
            self.sleeper(delay)


def _retry_after_seconds(headers: dict[str, str], body: object) -> float:
    if isinstance(body, dict) and body.get("retry_after") is not None:
        try:
            return max(0.0, float(body["retry_after"]))
        except (TypeError, ValueError):
            pass
    hdr = headers.get("retry-after")
    if hdr is not None:
        try:
            return max(0.0, float(hdr))
        except (TypeError, ValueError):
            pass
    return 1.0


def _is_global(headers: dict[str, str], body: object) -> bool:
    if headers.get("x-ratelimit-global") is not None:
        return True
    if isinstance(body, dict):
        return bool(body.get("global"))
    return False
