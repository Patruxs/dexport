"""The facade that wires the whole pipeline together.

``Dexport.acquire`` runs the full pipeline (see docs/ARCHITECTURE.md) — launcher -> attach ->
header snapshot -> api core + rate limiter + resolver — and hands back a ready
object. Use it as a context manager so the CDP session is always released and
the resolver cache is persisted on exit.
"""

from __future__ import annotations

from typing import Self

from .api import ApiCore
from .config import Paths, Settings, load_cache, save_cache
from .headers import capture_headers
from .launcher import ensure_discord
from .ratelimit import RateLimiter
from .resolver import Resolver
from .session import Session


class Dexport:
    """A live, authenticated handle on the user's Discord session."""

    def __init__(
        self,
        session: Session,
        api: ApiCore,
        resolver: Resolver,
        paths: Paths | None = None,
    ) -> None:
        self.session = session
        self.api = api
        self.resolver = resolver
        self._paths = paths

    @classmethod
    def acquire(
        cls,
        *,
        settings: Settings | None = None,
        force_restart: bool = False,
        paths: Paths | None = None,
    ) -> Self:
        """Run the whole pipeline and return a ready handle.

        ``settings`` defaults to :meth:`Settings.load` (config file +
        environment); the CLI layers its flags on top before calling this.
        """
        paths = paths or Paths.default()
        settings = settings or Settings.load(paths)

        endpoint = ensure_discord(
            settings.port,
            binary_override=settings.discord_binary,
            force_restart=force_restart,
            wait_timeout=settings.launch_timeout,
        )
        session = Session.connect(endpoint)
        # From here on the session owns a live CDP connection + Playwright
        # subprocess; release it if any later step raises, since the caller
        # never receives (and so can never close) a Dexport object.
        try:
            headers = capture_headers(session)
            limiter = RateLimiter(
                floor_min=settings.floor_delay_min,
                floor_max=settings.floor_delay_max,
            )
            api = ApiCore(
                session,
                headers,
                limiter,
                # The in-page fetch must be same-origin with the app page; see
                # api.rebase_url. Read after capture_headers, which reloads.
                origin=session.origin,
                header_refresh=lambda: capture_headers(session),
            )
            resolver = Resolver(api, load_cache(paths))
            return cls(session, api, resolver, paths)
        except Exception:
            session.close()
            raise

    def save(self) -> None:
        """Persist the resolver cache (the resolver owns and mutates it)."""
        save_cache(self.resolver.cache, self._paths)

    def close(self) -> None:
        try:
            self.save()
        finally:
            self.session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
