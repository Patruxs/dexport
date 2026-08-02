"""Typer CLI tests, driven through ``CliRunner`` with a fake Discord handle.

Nothing here touches Discord, the network, or the real ``~/.dexport``:

* ``Dexport.acquire`` is monkeypatched to hand back :class:`FakeDexport`
  (a ``FakeApi`` + a real ``Resolver`` over the conftest cache), or to raise
  when a code path must never reach Discord (``--dry-run --channel-id``).
* ``human_pause`` is replaced by a recording no-op so nothing sleeps.
* ``DEXPORT_HOME`` is redirected to a temp dir by the autouse conftest fixture.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from conftest import FakeApi
from typer.testing import CliRunner

from dexport import __version__
from dexport.api import DISCORD_API_BASE, ApiRequest
from dexport.cli import app
from dexport.cli.common import warn_tos_once
from dexport.cli.read import default_export_path
from dexport.config import DEFAULT_CDP_PORT, Paths
from dexport.errors import LauncherError
from dexport.messages import (
    add_reaction_request,
    delete_message_request,
    edit_message_request,
    send_message_request,
)
from dexport.resolver import Resolver

#: Plain, fixed-width rich output so assertions don't depend on the terminal.
PLAIN_ENV = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}

CHANNEL_ID = "123456789012345678"
MESSAGES_URL = f"{DISCORD_API_BASE}/channels/{CHANNEL_ID}/messages"

#: The order commands must appear in ``dexport --help``.
COMMANDS = [
    "whoami",
    "guilds",
    "channels",
    "read",
    "export",
    "send",
    "reply",
    "react",
    "edit",
    "delete",
    "configure",
]

#: Discord returns newest first; the CLI must show/export them oldest first.
MESSAGES_NEWEST_FIRST = [
    {
        "id": "2",
        "content": "second",
        "author": {"username": "bob"},
        "timestamp": "2026-08-26T10:01:00+00:00",
    },
    {
        "id": "1",
        "content": "first",
        "author": {"username": "alice"},
        "timestamp": "2026-08-26T10:00:00+00:00",
    },
]


# --------------------------------------------------------------------------
# Fakes and helpers
# --------------------------------------------------------------------------


class FakeDexport:
    """What ``connect()`` hands to a command: ``.api`` + ``.resolver`` + lifecycle."""

    def __init__(self, api: FakeApi, cache: dict[str, Any]) -> None:
        self.api = api
        self.resolver = Resolver(api, cache)
        self.acquire_calls: list[dict[str, Any]] = []
        self.pauses: list[tuple[Any, ...]] = []
        self.saved = 0
        self.closed = 0

    def save(self) -> None:
        self.saved += 1

    def close(self) -> None:
        self.save()
        self.closed += 1

    def __enter__(self) -> FakeDexport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner(env=PLAIN_ENV)


@pytest.fixture
def fake_dx(fake_api, resolver_cache, monkeypatch) -> FakeDexport:
    """Route ``connect()`` to a FakeDexport; record acquire kwargs and pauses."""
    dx = FakeDexport(fake_api, resolver_cache)

    def acquire(**kwargs: Any) -> FakeDexport:
        dx.acquire_calls.append(kwargs)
        return dx

    monkeypatch.setattr("dexport.cli.common.Dexport.acquire", acquire)
    monkeypatch.setattr("dexport.cli.common.human_pause", lambda *a, **k: dx.pauses.append(a))
    return dx


@pytest.fixture
def forbid_acquire(monkeypatch) -> list[dict[str, Any]]:
    """Make any attempt to reach Discord blow up; returns the (hopefully empty) calls."""
    calls: list[dict[str, Any]] = []

    def acquire(**kwargs: Any) -> FakeDexport:
        calls.append(kwargs)
        raise AssertionError("Dexport.acquire must not be called")

    monkeypatch.setattr("dexport.cli.common.Dexport.acquire", acquire)
    return calls


def has_flag(text: str, flag: str) -> bool:
    """True when ``flag`` appears as a whole token (``-g`` must not match ``--guild``)."""
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text) is not None


def parse_preview(output: str) -> tuple[str, str, Any]:
    """``(method, url, body)`` from a ``--dry-run`` preview; ``body`` is None if absent."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if "dry run" in line)
    method, url = lines[start + 1].split(" ", 1)
    rest = "\n".join(lines[start + 2 :]).strip()
    return method, url, (json.loads(rest) if rest else None)


# --------------------------------------------------------------------------
# 1-2. Help, version, no args
# --------------------------------------------------------------------------


def test_root_help_lists_commands_in_order(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    commands_section = result.output[result.output.index("Commands") :]
    listed = re.findall(r"^\W*([a-z]+)\s{2,}", commands_section, flags=re.MULTILINE)
    assert listed == COMMANDS


@pytest.mark.parametrize("flag", ["--port", "--restart", "--binary", "--version", "--help"])
def test_root_help_mentions_global_flag(runner, flag):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert has_flag(result.output, flag)


COMMAND_FLAGS = {
    "whoami": [],
    "guilds": ["--refresh"],
    "channels": ["-g", "--guild", "--guild-id", "--refresh"],
    "read": ["-g", "-c", "--guild-id", "--channel-id", "--limit", "-n"],
    "export": ["-g", "-c", "--guild-id", "--channel-id", "--limit", "--format", "-f", "-o"],
    "send": ["-m", "--message", "-g", "-c", "--guild-id", "--channel-id", "--yes", "--dry-run"],
    "reply": ["--to", "-m", "-g", "-c", "--guild-id", "--channel-id", "--yes", "--dry-run"],
    "react": [
        "--to",
        "-e",
        "--emoji",
        "-g",
        "-c",
        "--guild-id",
        "--channel-id",
        "--yes",
        "--dry-run",
    ],
    "edit": ["--to", "-m", "-g", "-c", "--guild-id", "--channel-id", "--yes", "--dry-run"],
    "delete": ["--to", "-g", "-c", "--guild-id", "--channel-id", "--yes", "--dry-run"],
    "configure": ["--port", "--binary", "--show"],
}


@pytest.mark.parametrize("command", COMMANDS)
def test_command_help_mentions_its_flags(runner, command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert f" {command} [OPTIONS]" in result.output
    missing = [flag for flag in COMMAND_FLAGS[command] if not has_flag(result.output, flag)]
    assert missing == []


def test_version_flag_prints_version(runner):
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"dexport {__version__}"


def test_no_args_shows_usage_without_touching_discord(runner, forbid_acquire):
    # The exit code here is the CLI framework's choice (it has changed across
    # Typer/click releases); what dexport owns is that help is shown and no
    # command runs.
    result = runner.invoke(app, [])
    assert "Usage:" in result.output
    assert "Commands" in result.output
    assert forbid_acquire == []


def test_missing_required_option_is_a_usage_error(runner, forbid_acquire):
    result = runner.invoke(app, ["send", "--dry-run", "--channel-id", CHANNEL_ID])
    assert result.exit_code == 2
    assert "Missing option" in result.output
    assert forbid_acquire == []


# --------------------------------------------------------------------------
# 3. --dry-run --channel-id never touches Discord
# --------------------------------------------------------------------------

DRY_RUN_CASES = [
    pytest.param(["send", "-m", "hi"], send_message_request(CHANNEL_ID, "hi"), id="send"),
    pytest.param(
        ["reply", "--to", "42", "-m", "hi"],
        send_message_request(CHANNEL_ID, "hi", reply_to="42"),
        id="reply",
    ),
    pytest.param(
        ["react", "--to", "42", "-e", "👍"],
        add_reaction_request(CHANNEL_ID, "42", "👍"),
        id="react-unicode",
    ),
    pytest.param(
        ["react", "--to", "42", "-e", "<:party:987>"],
        add_reaction_request(CHANNEL_ID, "42", "<:party:987>"),
        id="react-custom",
    ),
    pytest.param(
        ["edit", "--to", "42", "-m", "fixed"],
        edit_message_request(CHANNEL_ID, "42", "fixed"),
        id="edit",
    ),
    pytest.param(["delete", "--to", "42"], delete_message_request(CHANNEL_ID, "42"), id="delete"),
]


@pytest.mark.parametrize(("args", "expected"), DRY_RUN_CASES)
def test_dry_run_previews_exactly_the_builder_request(
    runner, forbid_acquire, args: list[str], expected: ApiRequest
):
    result = runner.invoke(app, [*args, "--dry-run", "--channel-id", CHANNEL_ID])
    assert result.exit_code == 0, result.output
    method, url, body = parse_preview(result.output)
    assert method == expected.method
    assert url == expected.url
    assert url == DISCORD_API_BASE + expected.path
    assert body == expected.body
    assert forbid_acquire == []


def test_dry_run_send_shows_full_url_and_json_body(runner, forbid_acquire):
    result = runner.invoke(app, ["send", "-m", "hi", "--dry-run", "--channel-id", CHANNEL_ID])
    assert result.exit_code == 0, result.output
    assert f"POST {MESSAGES_URL}" in result.output
    assert '"content": "hi"' in result.output
    assert forbid_acquire == []


def test_dry_run_reply_body_has_message_reference(runner, forbid_acquire):
    result = runner.invoke(
        app, ["reply", "--to", "42", "-m", "hi", "--dry-run", "--channel-id", CHANNEL_ID]
    )
    assert result.exit_code == 0, result.output
    _method, url, body = parse_preview(result.output)
    assert url == MESSAGES_URL
    assert body == {
        "content": "hi",
        "message_reference": {
            "channel_id": CHANNEL_ID,
            "message_id": "42",
            "fail_if_not_exists": False,
        },
    }
    assert forbid_acquire == []


@pytest.mark.parametrize(
    ("emoji", "segment"),
    [("👍", "%F0%9F%91%8D"), ("<:party:987>", "party%3A987"), ("<a:wave:55>", "wave%3A55")],
)
def test_dry_run_react_percent_encodes_emoji(runner, forbid_acquire, emoji, segment):
    result = runner.invoke(
        app, ["react", "--to", "42", "-e", emoji, "--dry-run", "--channel-id", CHANNEL_ID]
    )
    assert result.exit_code == 0, result.output
    method, url, body = parse_preview(result.output)
    assert method == "PUT"
    assert url == f"{MESSAGES_URL}/42/reactions/{segment}/@me"
    assert body is None
    assert forbid_acquire == []


def test_dry_run_delete_has_no_body(runner, forbid_acquire):
    result = runner.invoke(app, ["delete", "--to", "42", "--dry-run", "--channel-id", CHANNEL_ID])
    assert result.exit_code == 0, result.output
    assert parse_preview(result.output) == ("DELETE", f"{MESSAGES_URL}/42", None)
    assert forbid_acquire == []


def test_dry_run_with_channel_name_resolves_but_sends_nothing(runner, fake_dx):
    result = runner.invoke(
        app, ["send", "-g", "cu dem", "-c", "luoi chat tong", "-m", "hi", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert parse_preview(result.output) == (
        "POST",
        f"{DISCORD_API_BASE}/channels/10/messages",
        {"content": "hi"},
    )
    assert fake_dx.api.calls == []
    assert fake_dx.pauses == []
    assert len(fake_dx.acquire_calls) == 1


# --------------------------------------------------------------------------
# 4. Target validation
# --------------------------------------------------------------------------


def test_send_without_channel_fails(runner, fake_dx):
    result = runner.invoke(app, ["send", "-m", "hi", "--dry-run"])
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "Provide a channel" in result.output
    assert fake_dx.api.calls == []
    assert fake_dx.closed == 1  # the session is released even on failure


def test_send_with_channel_name_but_no_guild_fails(runner, fake_dx):
    result = runner.invoke(app, ["send", "-c", "luoi chat tong", "-m", "hi", "--yes"])
    assert result.exit_code == 1
    assert "Provide a guild" in result.output
    assert fake_dx.api.calls == []


def test_channels_without_guild_fails(runner, fake_dx):
    result = runner.invoke(app, ["channels"])
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "Provide -g/--guild" in result.output


# --------------------------------------------------------------------------
# 5. configure
# --------------------------------------------------------------------------

CONFIG_KEYS = {"port", "discord_binary", "floor_delay_min", "floor_delay_max"}


def _shown_config(output: str) -> dict[str, Any]:
    """The JSON object ``configure --show`` prints (before the ``config:`` line)."""
    return json.loads(output[: output.rindex("}") + 1])


def test_configure_show_prints_defaults_and_path(runner, dexport_home):
    result = runner.invoke(app, ["configure", "--show"])
    assert result.exit_code == 0, result.output
    shown = _shown_config(result.output)
    assert set(shown) == CONFIG_KEYS
    assert shown["port"] == DEFAULT_CDP_PORT
    assert shown["discord_binary"] is None
    assert f"config: {dexport_home / 'config.json'}" in result.output
    assert not (dexport_home / "config.json").exists()  # --show alone writes nothing


def test_configure_without_flags_behaves_like_show(runner):
    result = runner.invoke(app, ["configure"])
    assert result.exit_code == 0, result.output
    assert set(_shown_config(result.output)) == CONFIG_KEYS
    assert "config:" in result.output


def test_configure_saves_port_and_binary(runner, dexport_home):
    result = runner.invoke(app, ["configure", "--port", "4321", "--binary", "/x"])
    assert result.exit_code == 0, result.output
    assert "Saved" in result.output
    saved = json.loads((dexport_home / "config.json").read_text(encoding="utf-8"))
    assert saved["port"] == 4321
    assert saved["discord_binary"] == "/x"

    shown = _shown_config(runner.invoke(app, ["configure", "--show"]).output)
    assert (shown["port"], shown["discord_binary"]) == (4321, "/x")


def test_configure_never_persists_env_port(runner, dexport_home):
    assert runner.invoke(app, ["configure", "--port", "4321"]).exit_code == 0

    result = runner.invoke(app, ["configure", "--binary", "/x"], env={"DEXPORT_PORT": "5000"})
    assert result.exit_code == 0, result.output
    saved = json.loads((dexport_home / "config.json").read_text(encoding="utf-8"))
    assert saved["port"] == 4321
    assert saved["discord_binary"] == "/x"


# --------------------------------------------------------------------------
# 6. Commands that need Discord, through the fake
# --------------------------------------------------------------------------


def test_whoami_prints_account(runner, fake_dx):
    fake_dx.api.queue(200, {"id": "42", "username": "pat", "global_name": "Pat"})
    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 0, result.output
    assert "Logged in as Pat (@pat)" in result.output
    assert "(42)" in result.output
    assert fake_dx.api.calls == [("GET", "/users/@me", None)]
    assert fake_dx.closed == 1


def test_guilds_lists_cached_guilds_sorted_case_insensitively(runner, fake_dx):
    fake_dx.resolver.cache["guilds"] = [
        {"id": "2", "name": "beta"},
        {"id": "3", "name": "Zeta"},
        {"id": "1", "name": "Alpha"},
    ]
    result = runner.invoke(app, ["guilds"])
    assert result.exit_code == 0, result.output
    assert "3 guilds" in result.output
    assert "1  Alpha" in result.output
    positions = [result.output.index(name) for name in ("Alpha", "beta", "Zeta")]
    assert positions == sorted(positions)
    assert fake_dx.api.calls == []  # served from the cache


def test_guilds_refresh_refetches_and_persists(runner, fake_dx):
    fake_dx.api.queue(200, [{"id": "7", "name": "fresh"}])
    result = runner.invoke(app, ["guilds", "--refresh"])
    assert result.exit_code == 0, result.output
    assert fake_dx.api.calls == [("GET", "/users/@me/guilds", None)]
    assert "7  fresh" in result.output
    assert "random server" not in result.output
    assert fake_dx.resolver.cache["guilds"] == [{"id": "7", "name": "fresh"}]
    assert fake_dx.saved == 1


def test_channels_by_fuzzy_guild_name(runner, fake_dx):
    result = runner.invoke(app, ["channels", "-g", "cu dem"])
    assert result.exit_code == 0, result.output
    assert "cú đêm: 3 channels" in result.output
    for cid, name in (("10", "lười-chat-tổng"), ("11", "voice-hangout"), ("12", "thông-báo")):
        assert f"{cid}  #{name}" in result.output
    assert fake_dx.api.calls == []


def test_channels_by_uncached_guild_id_fetches(runner, fake_dx):
    fake_dx.api.queue(200, [{"id": "50", "name": "general", "type": 0}])
    result = runner.invoke(app, ["channels", "--guild-id", "999"])
    assert result.exit_code == 0, result.output
    assert fake_dx.api.calls == [("GET", "/guilds/999/channels", None)]
    assert "999: 1 channels" in result.output
    assert "50  #general" in result.output


def test_read_renders_messages_oldest_first(runner, fake_dx):
    fake_dx.api.queue(200, MESSAGES_NEWEST_FIRST)
    result = runner.invoke(app, ["read", "--channel-id", CHANNEL_ID, "--limit", "5"])
    assert result.exit_code == 0, result.output
    assert fake_dx.api.calls == [("GET", f"/channels/{CHANNEL_ID}/messages?limit=5", None)]
    assert f"channel {CHANNEL_ID}" in result.output
    assert result.output.index("alice") < result.output.index("bob")
    assert result.output.index("first") < result.output.index("second")


def test_read_by_names_resolves_and_shows_empty_channel(runner, fake_dx):
    fake_dx.api.queue(200, [])
    result = runner.invoke(app, ["read", "-g", "cu dem", "-c", "luoi chat tong"])
    assert result.exit_code == 0, result.output
    assert fake_dx.api.calls == [("GET", "/channels/10/messages?limit=50", None)]
    assert "cú đêm #lười-chat-tổng" in result.output
    assert "(no messages)" in result.output


def test_export_json_writes_file_oldest_first(runner, fake_dx, tmp_path):
    fake_dx.api.queue(200, MESSAGES_NEWEST_FIRST)
    out = tmp_path / "out.json"
    result = runner.invoke(
        app, ["export", "--channel-id", CHANNEL_ID, "-f", "json", "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "fetched 2..." in result.output
    assert "Exported 2 messages" in result.output
    assert str(out) in result.output
    assert [m["id"] for m in json.loads(out.read_text(encoding="utf-8"))] == ["1", "2"]


def test_export_default_path_is_markdown_in_cwd(runner, fake_dx, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_dx.api.queue(200, MESSAGES_NEWEST_FIRST)
    result = runner.invoke(app, ["export", "--channel-id", CHANNEL_ID])
    assert result.exit_code == 0, result.output
    out = tmp_path / f"channel-{CHANNEL_ID}.md"
    assert f"Exported 2 messages -> {out.name}" in result.output
    text = out.read_text(encoding="utf-8")
    assert text.startswith(f"# channel {CHANNEL_ID}")
    assert text.index("first") < text.index("second")


def test_export_unknown_format_fails_without_writing(runner, fake_dx, tmp_path):
    fake_dx.api.queue(200, [])
    out = tmp_path / "out.xml"
    result = runner.invoke(
        app, ["export", "--channel-id", CHANNEL_ID, "--format", "xml", "-o", str(out)]
    )
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "xml" in result.output
    assert not out.exists()


def test_send_resolves_names_confirms_pauses_and_posts(runner, fake_dx):
    fake_dx.api.queue(200, {"id": "999"})
    result = runner.invoke(
        app, ["send", "-g", "cu dem", "-c", "luoi chat tong", "-m", "hi", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert fake_dx.api.calls == [("POST", "/channels/10/messages", {"content": "hi"})]
    assert "Sent message 999 to cú đêm #lười-chat-tổng" in result.output
    assert len(fake_dx.pauses) == 1


def test_send_declined_at_prompt_sends_nothing(runner, fake_dx):
    result = runner.invoke(app, ["send", "--channel-id", CHANNEL_ID, "-m", "hi"], input="n\n")
    assert result.exit_code == 0, result.output
    assert f"Send message in channel {CHANNEL_ID}?" in result.output
    assert fake_dx.api.calls == []
    assert fake_dx.pauses == []
    assert "Sent" not in result.output


def test_send_accepted_at_prompt_posts(runner, fake_dx):
    fake_dx.api.queue(200, {"id": "999"})
    result = runner.invoke(app, ["send", "--channel-id", CHANNEL_ID, "-m", "hi"], input="y\n")
    assert result.exit_code == 0, result.output
    assert fake_dx.api.calls == [("POST", f"/channels/{CHANNEL_ID}/messages", {"content": "hi"})]
    assert "Sent message 999" in result.output


EXECUTE_CASES = [
    pytest.param(
        ["send", "-m", "hi"],
        (200, {"id": "999"}),
        ("POST", f"/channels/{CHANNEL_ID}/messages", {"content": "hi"}),
        "Sent message 999",
        id="send",
    ),
    pytest.param(
        ["reply", "--to", "42", "-m", "hi"],
        (200, {"id": "1000"}),
        (
            "POST",
            f"/channels/{CHANNEL_ID}/messages",
            {
                "content": "hi",
                "message_reference": {
                    "channel_id": CHANNEL_ID,
                    "message_id": "42",
                    "fail_if_not_exists": False,
                },
            },
        ),
        "Replied with message 1000",
        id="reply",
    ),
    pytest.param(
        ["react", "--to", "42", "-e", "👍"],
        (204, None),
        ("PUT", f"/channels/{CHANNEL_ID}/messages/42/reactions/%F0%9F%91%8D/@me", None),
        "Reacted 👍 to 42",
        id="react",
    ),
    pytest.param(
        ["edit", "--to", "42", "-m", "fixed"],
        (200, {"id": "42"}),
        ("PATCH", f"/channels/{CHANNEL_ID}/messages/42", {"content": "fixed"}),
        "Edited message 42",
        id="edit",
    ),
    pytest.param(
        ["delete", "--to", "42"],
        (204, None),
        ("DELETE", f"/channels/{CHANNEL_ID}/messages/42", None),
        "Deleted message 42",
        id="delete",
    ),
]


@pytest.mark.parametrize(("args", "response", "expected_call", "done"), EXECUTE_CASES)
def test_write_verb_executes_request_and_reports(
    runner, fake_dx, args, response, expected_call, done
):
    fake_dx.api.queue(*response)
    result = runner.invoke(app, [*args, "--channel-id", CHANNEL_ID, "--yes"])
    assert result.exit_code == 0, result.output
    assert fake_dx.api.calls == [expected_call]
    assert done in result.output
    assert f"channel {CHANNEL_ID}" in result.output
    assert len(fake_dx.pauses) == 1


def test_api_error_is_reported_as_error_line(runner, fake_dx):
    fake_dx.api.queue(403, {"message": "Missing Access"})
    result = runner.invoke(app, ["send", "--channel-id", CHANNEL_ID, "-m", "hi", "--yes"])
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "403" in result.output
    assert "Missing Access" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert fake_dx.closed == 1
