"""The ``/dexport`` slash command: rendering, file placement, and the
``install-agent`` command that writes it.

Nothing here touches the real home directory — ``HOME`` (and ``USERPROFILE``,
for ``Path.home()`` on Windows) is redirected to a temp dir.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import replace
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


def test_pi_frontmatter_carries_the_argument_hint():
    """pi shows argument-hint in its /-autocomplete, so it must be there."""
    head = agents.render(agents.TARGETS_BY_KEY["pi"]).split("---")[1]
    assert f"description: {agents.DESCRIPTION}" in head
    assert f"argument-hint: {agents.ARGUMENT_HINT}" in head


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------


SKILLED = [t for t in agents.TARGETS if t.skill is not None]


def test_every_agent_ships_a_skill():
    """SKILL.md is one open format all six read; only the directory differs.
    A new target without one would silently be command-only, which is the bug
    this whole section exists to prevent."""
    assert list(agents.TARGETS) == SKILLED


def test_skill_directories_match_each_vendor():
    """Written down because these are not guessable and not interchangeable --
    Codex in particular has no ``.codex/skills`` and reads ``.agents`` instead."""
    assert {t.key: t.skill.user_dir for t in SKILLED} == {
        "claude": ".claude/skills",
        "codex": ".agents/skills",
        "cursor": ".cursor/skills",
        "gemini": ".gemini/skills",
        "opencode": ".config/opencode/skills",
        "pi": ".pi/agent/skills",
    }


def test_skill_name_is_a_valid_agent_skills_identifier():
    """The spec: 1-64 chars, lowercase alphanumeric and hyphens, no leading,
    trailing or doubled hyphen, and it must match the parent directory."""
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", agents.NAME)
    assert 1 <= len(agents.NAME) <= 64
    assert agents.skill_path(SKILLED[0], home=Path("/h")).parent.name == agents.NAME


def test_skill_description_fits_the_spec_limit():
    assert 0 < len(agents.SKILL_DESCRIPTION) <= 1024


@pytest.mark.parametrize("target", SKILLED, ids=lambda t: t.key)
def test_skill_frontmatter_parses_as_yaml_and_carries_the_prompt(target):
    text = agents.render_skill(target)
    head, body = text.split("---\n")[1], text.split("---\n\n", 1)[1]
    front = dict(line.split(": ", 1) for line in head.strip().splitlines())
    assert front["name"] == agents.NAME
    assert front["description"] == agents.SKILL_DESCRIPTION
    assert "Answer questions about my Discord" in body
    assert "Never run `send`" in body


def test_skill_description_stays_a_safe_unquoted_yaml_scalar():
    """`#` starts a comment and `: ` starts a mapping, so neither may appear."""
    assert " #" not in agents.SKILL_DESCRIPTION
    assert ": " not in agents.SKILL_DESCRIPTION


def test_skill_has_no_argument_slot():
    """A skill is loaded by the model, not invoked with the user's words."""
    for target in SKILLED:
        assert "$ARGUMENTS" not in agents.render_skill(target)


def test_only_claude_gets_the_allowed_tools_field():
    """ALLOWED_TOOLS is comma-separated, which only Claude Code accepts. The
    spec says space-separated, so anyone else would split it into rubbish."""
    for target in SKILLED:
        wanted = target.key == "claude"
        assert ("allowed-tools:" in agents.render_skill(target)) is wanted
    assert ", " in agents.ALLOWED_TOOLS


def test_no_skill_disables_model_invocation():
    """Cursor, pi and Claude Code all honour this field, and setting it would
    undo the entire point of shipping a skill."""
    for target in SKILLED:
        assert "disable-model-invocation" not in agents.render_skill(target)


def test_skill_path_user_and_project_scopes(tmp_path):
    claude = agents.TARGETS_BY_KEY["claude"]
    assert agents.skill_path(claude, home=tmp_path) == tmp_path / ".claude/skills/dexport/SKILL.md"
    root = tmp_path / "proj"
    assert agents.skill_path(claude, home=tmp_path, root=root) == (
        root / ".claude/skills/dexport/SKILL.md"
    )


def test_skill_path_is_none_without_skill_support(tmp_path):
    """No shipped target is skill-less today, but the field is optional and
    skill_path has to keep answering for one that is."""
    bare = replace(agents.TARGETS_BY_KEY["cursor"], skill=None)
    assert agents.skill_path(bare, home=tmp_path) is None
    assert agents.skill_path(bare, home=tmp_path, root=tmp_path) is None


def test_codex_scopes_differ_between_its_command_and_its_skill(tmp_path):
    """Codex keeps prompts user-level but takes a project-level skill, so the
    two files cannot share one scope check."""
    codex = agents.TARGETS_BY_KEY["codex"]
    assert agents.target_path(codex, home=tmp_path, root=tmp_path) is None
    assert agents.skill_path(codex, home=tmp_path, root=tmp_path) == (
        tmp_path / ".agents/skills/dexport/SKILL.md"
    )


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


def test_pi_user_and_project_scopes_are_different_suffixes(tmp_path):
    """Global prompts live under ~/.pi/agent, project ones under a bare .pi/."""
    pi = agents.TARGETS_BY_KEY["pi"]
    assert agents.target_path(pi, home=tmp_path) == tmp_path / ".pi/agent/prompts/dexport.md"
    root = tmp_path / "proj"
    assert agents.target_path(pi, home=tmp_path, root=root) == root / ".pi/prompts/dexport.md"


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


def test_install_agent_writes_the_skill_next_to_the_command(home):
    """The regression this exists for: a slash command alone never fires on its
    own, so plain-language questions used to miss dexport entirely."""
    (home / ".codex").mkdir()

    result = runner.invoke(app, ["install-agent"])

    assert result.exit_code == 0, result.output
    skill = home / ".agents/skills/dexport/SKILL.md"
    assert (home / ".codex/prompts/dexport.md").exists()
    assert skill.exists()
    assert agents.SKILL_DESCRIPTION in skill.read_text(encoding="utf-8")
    assert "plain language" in result.output


@pytest.mark.parametrize("target", agents.TARGETS, ids=lambda t: t.key)
def test_install_agent_writes_a_skill_for_every_agent(home, target):
    result = runner.invoke(app, ["install-agent", "-t", target.key])

    assert result.exit_code == 0, result.output
    assert agents.skill_path(target, home=home).exists()


def test_install_agent_skill_respects_force(home):
    path = home / ".claude/skills/dexport/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("mine", encoding="utf-8")

    assert runner.invoke(app, ["install-agent", "-t", "claude"]).exit_code == 0
    assert path.read_text(encoding="utf-8") == "mine"

    assert runner.invoke(app, ["install-agent", "-t", "claude", "--force"]).exit_code == 0
    assert "Never run `send`" in path.read_text(encoding="utf-8")


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


def test_install_agent_project_scope_installs_what_the_agent_supports(home, tmp_path, monkeypatch):
    """Codex has no project prompts but does have project skills: it must get
    the skill rather than be skipped outright."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["install-agent", "-t", "codex", "--project"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".agents/skills/dexport/SKILL.md").exists()
    assert not (tmp_path / ".codex").exists()


def test_install_agent_skips_an_agent_with_no_project_scope_at_all(home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    codex = agents.TARGETS_BY_KEY["codex"]
    user_only = replace(codex, skill=replace(codex.skill, project_dir=None))
    monkeypatch.setitem(agents.TARGETS_BY_KEY, "codex", user_only)

    result = runner.invoke(app, ["install-agent", "-t", "codex", "--project"])

    assert result.exit_code == 0, result.output
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
