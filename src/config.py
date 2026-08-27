"""On-disk configuration and cache.

Two files live under ``$DEXPORT_HOME`` (default ``~/.dexport``):

* ``config.json`` — user preferences, modelled by :class:`Settings`.
* ``cache.json`` — resolver cache of guild/channel id<->name mappings so we
  don't hit the API on every invocation.
* ``notice-shown`` — marker recording that the one-time Terms-of-Service
  notice has already been printed.

Neither file ever stores request headers or the authorization token; those are
kept in RAM only for the lifetime of a single command.

Precedence for settings is **CLI flag > environment variable > config.json >
built-in default**. The CLI layer applies flags; :meth:`Settings.load` applies
the rest.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

from .launcher import DEFAULT_LAUNCH_TIMEOUT
from .ratelimit import DEFAULT_FLOOR_MAX, DEFAULT_FLOOR_MIN

DEFAULT_CDP_PORT = 9222

ENV_HOME = "DEXPORT_HOME"
ENV_PORT = "DEXPORT_PORT"
ENV_DISCORD_BINARY = "DEXPORT_DISCORD_BINARY"
ENV_LAUNCH_TIMEOUT = "DEXPORT_LAUNCH_TIMEOUT"

_Num = TypeVar("_Num", int, float)


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Paths:
    """Where dexport keeps its files."""

    home: Path

    @property
    def config(self) -> Path:
        return self.home / "config.json"

    @property
    def cache(self) -> Path:
        return self.home / "cache.json"

    @property
    def notice(self) -> Path:
        """Marker for the one-time Terms-of-Service notice (see ``cli.common``)."""
        return self.home / "notice-shown"

    @classmethod
    def default(cls, env: Mapping[str, str] | None = None) -> Paths:
        """``$DEXPORT_HOME`` if set, else ``~/.dexport`` (resolved at call time)."""
        env = os.environ if env is None else env
        home = env.get(ENV_HOME)
        return cls(Path(home) if home else Path.home() / ".dexport")


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


@dataclass
class Settings:
    """User preferences persisted in ``config.json``.

    Field names are the JSON keys; keep them stable — they are user-facing.
    """

    port: int = DEFAULT_CDP_PORT
    discord_binary: str | None = None
    floor_delay_min: float = DEFAULT_FLOOR_MIN
    floor_delay_max: float = DEFAULT_FLOOR_MAX
    launch_timeout: float = DEFAULT_LAUNCH_TIMEOUT

    # -- (de)serialisation ------------------------------------------------
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Settings:
        """Build from a JSON dict, falling back to defaults for bad/missing values."""
        binary = data.get("discord_binary")
        return cls(
            port=_coerce(int, data.get("port"), DEFAULT_CDP_PORT),
            discord_binary=str(binary) if binary else None,
            floor_delay_min=_coerce(float, data.get("floor_delay_min"), DEFAULT_FLOOR_MIN),
            floor_delay_max=_coerce(float, data.get("floor_delay_max"), DEFAULT_FLOOR_MAX),
            launch_timeout=_coerce(float, data.get("launch_timeout"), DEFAULT_LAUNCH_TIMEOUT),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # -- loading / saving -------------------------------------------------
    @classmethod
    def load_file(cls, paths: Paths | None = None) -> Settings:
        """Settings as persisted on disk (defaults + file), WITHOUT env overrides.

        ``configure`` mutates and re-saves this so that transient environment
        overrides (DEXPORT_PORT, DEXPORT_DISCORD_BINARY) are never baked into
        the file.
        """
        paths = paths or Paths.default()
        return cls.from_dict(_read_json(paths.config))

    @classmethod
    def load(cls, paths: Paths | None = None, env: Mapping[str, str] | None = None) -> Settings:
        """Effective settings: file overlaid with environment overrides."""
        return cls.load_file(paths).with_env_overrides(env)

    def with_env_overrides(self, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        updates: dict[str, Any] = {}
        port = env.get(ENV_PORT)
        if port and port.isdecimal():
            updates["port"] = int(port)
        binary = env.get(ENV_DISCORD_BINARY)
        if binary:
            updates["discord_binary"] = binary
        timeout = _positive_float(env.get(ENV_LAUNCH_TIMEOUT))
        if timeout is not None:
            updates["launch_timeout"] = timeout
        return replace(self, **updates) if updates else self

    def with_overrides(
        self, *, port: int | None = None, discord_binary: str | None = None
    ) -> Settings:
        """Explicit (e.g. CLI flag) values win; ``None`` means "not given"."""
        updates: dict[str, Any] = {}
        if port is not None:
            updates["port"] = port
        if discord_binary is not None:
            updates["discord_binary"] = discord_binary
        return replace(self, **updates) if updates else self

    def save(self, paths: Paths | None = None) -> None:
        paths = paths or Paths.default()
        _write_json(paths.config, self.to_dict())


# --------------------------------------------------------------------------
# Resolver cache
# --------------------------------------------------------------------------


def load_cache(paths: Paths | None = None) -> dict[str, Any]:
    """Raw cache dict (``{}`` when missing/corrupt); the resolver fills in keys."""
    paths = paths or Paths.default()
    return _read_json(paths.cache)


def save_cache(cache: Mapping[str, Any], paths: Paths | None = None) -> None:
    paths = paths or Paths.default()
    _write_json(paths.cache, cache)


# --------------------------------------------------------------------------
# JSON file helpers
# --------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    """Parse ``path`` as a JSON object; missing/corrupt/non-object → ``{}``."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Atomically write ``data`` as pretty JSON, creating the directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _positive_float(raw: str | None) -> float | None:
    """Parse an env value as a positive float; ``None`` when unset or nonsense.

    A zero or negative timeout would turn every launch into an instant failure,
    so it is treated as "not given" rather than honoured.
    """
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _coerce(cast: type[_Num], value: Any, default: _Num) -> _Num:
    if value is None:
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default
