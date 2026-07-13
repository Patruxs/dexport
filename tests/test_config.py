import json
from pathlib import Path

import pytest

from dexport.config import (
    DEFAULT_CDP_PORT,
    Paths,
    Settings,
    load_cache,
    save_cache,
)


def test_paths_default_honours_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEXPORT_HOME", str(tmp_path))
    paths = Paths.default()
    assert paths.home == tmp_path
    assert paths.config == tmp_path / "config.json"
    assert paths.cache == tmp_path / "cache.json"


def test_paths_default_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("DEXPORT_HOME", raising=False)
    assert Paths.default().home.name == ".dexport"


def test_paths_default_explicit_env_ignores_os_environ(tmp_path, monkeypatch):
    monkeypatch.setenv("DEXPORT_HOME", str(tmp_path / "from-os-environ"))
    assert Paths.default(env={}).home == Path.home() / ".dexport"
    explicit = tmp_path / "explicit"
    assert Paths.default(env={"DEXPORT_HOME": str(explicit)}).home == explicit
