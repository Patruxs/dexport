"""The ``/dexport`` slash command: rendering, file placement, and the
``install-agent`` command that writes it.

Nothing here touches the real home directory — ``HOME`` (and ``USERPROFILE``,
for ``Path.home()`` on Windows) is redirected to a temp dir.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dexport import agents
from dexport.cli import app

runner = CliRunner()

WRITE_VERBS = ("send", "reply", "react", "edit", "delete")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake ``$HOME`` that :func:`pathlib.Path.home` resolves to."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    assert Path.home() == fake
    return fake


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_allowlist_has_no_write_verb():
    """The point of the allowlist: an installed /dexport cannot post."""
    for verb in WRITE_VERBS:
        assert f"dexport {verb}" not in agents.ALLOWED_TOOLS


@pytest.mark.parametrize("target", agents.TARGETS, ids=lambda t: t.key)
def test_every_target_carries_the_prompt_and_its_argument_slot(target):
    text = agents.render(target)
    assert "Answer questions about my Discord" in text
    assert "Never run `send`" in text
    if target.argument_slot:
        assert target.argument_slot in text
    else:
        assert "follows below" in text


def test_generic_render_uses_dollar_arguments():
    assert "$ARGUMENTS" in agents.render()


def test_claude_frontmatter_is_complete():
    head = agents.render(agents.TARGETS_BY_KEY["claude"]).split("---")[1]
    assert f"description: {agents.DESCRIPTION}" in head
    assert f"argument-hint: {agents.ARGUMENT_HINT}" in head
    assert "allowed-tools: Bash(dexport guilds:*)" in head


def test_gemini_render_is_valid_toml():
    data = tomllib.loads(agents.render(agents.TARGETS_BY_KEY["gemini"]))
    assert data["description"] == agents.DESCRIPTION
    assert "{{args}}" in data["prompt"]


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------


def test_target_path_user_scope(tmp_path):
    claude = agents.TARGETS_BY_KEY["claude"]
    assert agents.target_path(claude, home=tmp_path) == tmp_path / ".claude/commands/dexport.md"


def test_target_path_project_scope(tmp_path):
    claude = agents.TARGETS_BY_KEY["claude"]
    path = agents.target_path(claude, home=tmp_path, root=tmp_path / "proj")
    assert path == tmp_path / "proj/.claude/commands/dexport.md"


def test_target_path_is_none_when_the_agent_has_no_project_scope(tmp_path):
    codex = agents.TARGETS_BY_KEY["codex"]
    assert codex.project_path is None
    assert agents.target_path(codex, home=tmp_path, root=tmp_path) is None


def test_detect_finds_only_agents_that_exist(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".config" / "opencode").mkdir(parents=True)
    assert [t.key for t in agents.detect(tmp_path)] == ["claude", "opencode"]


def test_detect_on_a_bare_home_finds_nothing(tmp_path):
    assert agents.detect(tmp_path) == []


def test_write_creates_parents_and_refuses_to_clobber(tmp_path):
    path = tmp_path / "a" / "b" / "dexport.md"
    assert agents.write(path, "first") is True
    assert agents.write(path, "second") is False
    assert path.read_text(encoding="utf-8") == "first"
    assert agents.write(path, "second", force=True) is True
    assert path.read_text(encoding="utf-8") == "second"


# --------------------------------------------------------------------------
# install-agent
# --------------------------------------------------------------------------


def test_install_agent_writes_every_detected_agent(home):
    (home / ".claude").mkdir()
    (home / ".gemini").mkdir()

    result = runner.invoke(app, ["install-agent"])

    assert result.exit_code == 0, result.output
    assert (home / ".claude/commands/dexport.md").exists()
    assert (home / ".gemini/commands/dexport.toml").exists()
    assert not (home / ".cursor/commands/dexport.md").exists()


def test_install_agent_target_beats_detection(home):
    (home / ".claude").mkdir()

    result = runner.invoke(app, ["install-agent", "-t", "cursor"])

    assert result.exit_code == 0, result.output
    assert (home / ".cursor/commands/dexport.md").exists()
    assert not (home / ".claude/commands/dexport.md").exists()


def test_install_agent_does_not_overwrite_without_force(home):
    path = home / ".claude/commands/dexport.md"
    path.parent.mkdir(parents=True)
    path.write_text("mine", encoding="utf-8")

    assert runner.invoke(app, ["install-agent", "-t", "claude"]).exit_code == 0
    assert path.read_text(encoding="utf-8") == "mine"

    assert runner.invoke(app, ["install-agent", "-t", "claude", "--force"]).exit_code == 0
    assert "Never run `send`" in path.read_text(encoding="utf-8")


def test_install_agent_project_scope(home, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.chdir(project)

    result = runner.invoke(app, ["install-agent", "-t", "claude", "--project"])

    assert result.exit_code == 0, result.output
    assert (project / ".claude/commands/dexport.md").exists()
    assert not (home / ".claude/commands/dexport.md").exists()


def test_install_agent_skips_agents_without_a_project_scope(home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install-agent", "-t", "codex", "--project"])
    assert result.exit_code == 0
    assert "skipped" in result.output


def test_install_agent_print_writes_nothing(home):
    (home / ".claude").mkdir()

    result = runner.invoke(app, ["install-agent", "--print"])

    assert result.exit_code == 0
    assert "$ARGUMENTS" in result.output
    assert not (home / ".claude/commands/dexport.md").exists()


def test_install_agent_print_with_one_target_renders_that_flavour(home):
    result = runner.invoke(app, ["install-agent", "-t", "gemini", "--print"])
    assert result.exit_code == 0
    assert result.output.startswith(f'description = "{agents.DESCRIPTION}"')


def test_install_agent_rejects_an_unknown_target(home):
    result = runner.invoke(app, ["install-agent", "-t", "emacs"])
    assert result.exit_code == 1
    assert "Unknown agent(s): emacs" in result.output


def test_install_agent_without_any_agent_installed_explains_itself(home):
    result = runner.invoke(app, ["install-agent"])
    assert result.exit_code == 1
    assert "No coding agent detected" in result.output
