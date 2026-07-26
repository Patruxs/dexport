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


def test_configure_does_not_persist_env_override(tmp_path, monkeypatch):
    # Regression: `configure --binary /x` with DEXPORT_PORT set must NOT bake
    # the transient env port into config.json.
    paths = Paths(tmp_path)
    monkeypatch.setenv("DEXPORT_PORT", "5000")

    # Simulate what the `configure` command does.
    conf = Settings.load_file(paths)
    conf.discord_binary = "/x"
    conf.save(paths)

    on_disk = json.loads(paths.config.read_text(encoding="utf-8"))
    assert on_disk["discord_binary"] == "/x"
    assert on_disk["port"] == DEFAULT_CDP_PORT  # not 5000 from the env

    # But the *effective* runtime config still honours the env override.
    assert Settings.load(paths).port == 5000


def test_env_overrides_are_validated():
    base = Settings()
    assert base.with_env_overrides({"DEXPORT_PORT": "1234"}).port == 1234
    assert base.with_env_overrides({"DEXPORT_PORT": "abc"}).port == DEFAULT_CDP_PORT
    assert base.with_env_overrides({"DEXPORT_DISCORD_BINARY": ""}).discord_binary is None
    assert base.with_env_overrides({"DEXPORT_DISCORD_BINARY": "/d"}).discord_binary == "/d"
    assert base.with_env_overrides({}) is base


def test_env_overrides_explicit_env_ignores_os_environ(monkeypatch):
    monkeypatch.setenv("DEXPORT_PORT", "7777")
    assert Settings().with_env_overrides({}).port == DEFAULT_CDP_PORT
    assert Settings().with_env_overrides().port == 7777


def test_cache_roundtrip_and_missing(tmp_path):
    paths = Paths(tmp_path)
    assert load_cache(paths) == {}
    save_cache({"guilds": [{"id": "1", "name": "x"}], "channels": {}}, paths)
    assert load_cache(paths)["guilds"] == [{"id": "1", "name": "x"}]
    assert not paths.cache.with_suffix(".json.tmp").exists()  # atomic write cleaned up


# --------------------------------------------------------------------------
# Settings.with_overrides (CLI flags)
# --------------------------------------------------------------------------


def test_with_overrides_port_only():
    base = Settings(discord_binary="/x", floor_delay_min=0.1, floor_delay_max=0.2)
    got = base.with_overrides(port=1)
    assert got == Settings(port=1, discord_binary="/x", floor_delay_min=0.1, floor_delay_max=0.2)


def test_with_overrides_binary_only():
    base = Settings(port=5)
    got = base.with_overrides(discord_binary="/y")
    assert got == Settings(port=5, discord_binary="/y")


def test_with_overrides_both():
    got = Settings().with_overrides(port=1, discord_binary="/y")
    assert (got.port, got.discord_binary) == (1, "/y")


def test_with_overrides_none_returns_same_object():
    base = Settings()
    assert base.with_overrides() is base
    assert base.with_overrides(port=None, discord_binary=None) is base


def test_with_overrides_port_zero_is_honoured():
    # The check must be ``is not None``, not truthiness.
    assert Settings(port=5).with_overrides(port=0).port == 0


def test_with_overrides_does_not_mutate_original():
    base = Settings()
    base.with_overrides(port=1, discord_binary="/y")
    assert base == Settings()


# --------------------------------------------------------------------------
# Precedence: CLI flag > env > config.json > default
# --------------------------------------------------------------------------


def test_load_precedence_flag_over_env_over_file(tmp_path):
    paths = Paths(tmp_path)
    Settings(port=1111).save(paths)

    assert Settings.load_file(paths).port == 1111
    effective = Settings.load(paths, env={"DEXPORT_PORT": "2222"})
    assert effective.port == 2222
    assert effective.with_overrides(port=3333).port == 3333


def test_load_reads_os_environ_when_env_not_given(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    Settings(port=1111).save(paths)
    monkeypatch.setenv("DEXPORT_PORT", "2222")
    assert Settings.load(paths).port == 2222


def test_load_falls_back_to_file_when_env_unset(tmp_path):
    paths = Paths(tmp_path)
    Settings(port=1111).save(paths)
    assert Settings.load(paths, env={}).port == 1111


def test_env_binary_overrides_file_but_is_not_persisted(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    Settings(discord_binary="/from-file").save(paths)
    monkeypatch.setenv("DEXPORT_DISCORD_BINARY", "/from-env")

    assert Settings.load(paths).discord_binary == "/from-env"

    conf = Settings.load_file(paths)
    assert conf.discord_binary == "/from-file"
    conf.port = 4000
    conf.save(paths)
    on_disk = json.loads(paths.config.read_text(encoding="utf-8"))
    assert on_disk["discord_binary"] == "/from-file"
    assert on_disk["port"] == 4000
