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


def test_settings_defaults_when_no_file(tmp_path):
    s = Settings.load_file(Paths(tmp_path))
    assert s == Settings()
    assert s.port == DEFAULT_CDP_PORT


def test_settings_roundtrip_preserves_json_keys(tmp_path):
    paths = Paths(tmp_path)
    Settings(port=4321, discord_binary="/x").save(paths)
    on_disk = json.loads(paths.config.read_text(encoding="utf-8"))
    # The on-disk format is user-facing; keep these keys stable.
    assert on_disk == {
        "port": 4321,
        "discord_binary": "/x",
        "floor_delay_min": 0.25,
        "floor_delay_max": 0.6,
    }
    assert Settings.load_file(paths) == Settings(port=4321, discord_binary="/x")


def test_settings_tolerates_bad_values(tmp_path):
    paths = Paths(tmp_path)
    paths.config.write_text(
        json.dumps({"port": "not-a-number", "floor_delay_min": None, "extra": 1}),
        encoding="utf-8",
    )
    s = Settings.load_file(paths)
    assert s.port == DEFAULT_CDP_PORT
    assert s.floor_delay_min == 0.25


def test_settings_corrupt_file_gives_defaults(tmp_path):
    paths = Paths(tmp_path)
    paths.config.write_text("{not json", encoding="utf-8")
    assert Settings.load_file(paths) == Settings()
