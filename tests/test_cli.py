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
