"""The ``/dexport`` slash command and skill, rendered for each coding agent.

One prompt (:data:`PROMPT`), several wrappers: every agent keeps its commands
in a different place and spells "the rest of what the user typed" differently.
:func:`render` produces the file body for a target, :func:`target_path` says
where it goes, and ``dexport install-agent`` writes it. Anything not listed in
:data:`TARGETS` is served by ``--print``.

A slash command only reaches the model when the user types it, so every target
also gets the same prompt as an Agent Skills ``SKILL.md`` (:func:`render_skill`
/ :func:`skill_path`), which the model loads on its own when a question is
about Discord -- that is what makes "what did I miss in #general?" work without
a leading ``/dexport``. ``SKILL.md`` is one open format (agentskills.io) that
all six agents read; only the directory differs.

The prompt is deliberately read-only: it allows the three read verbs and bans
the write ones, so an installed ``/dexport`` can never post as the user.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: File name (without extension) every agent will expose as ``/dexport``.
NAME = "dexport"
DESCRIPTION = "Read my Discord and answer questions about it"
ARGUMENT_HINT = "what you want to know"

#: Claude Code tool allowlist — read verbs only. Note what this does and does
#: not do: it *pre-approves* the listed commands, it does not forbid the rest.
#: Its value is that the write verbs stay outside the grant and so always hit a
#: permission prompt, which is where a channel-injected instruction gets caught.
ALLOWED_TOOLS = "Bash(dexport guilds:*), Bash(dexport channels:*), Bash(dexport export:*), Read"

#: Model-facing trigger text for the skill. Unlike :data:`DESCRIPTION` (a menu
#: label for a command the user picked) this one has to earn its own recall, so
#: it spells out the occasions. Keep it free of ``#`` and ``: `` -- it is
#: rendered as an unquoted YAML scalar.
SKILL_DESCRIPTION = (
    "Read the user's own Discord and answer questions about it with the dexport CLI. "
    "Use whenever the user asks about a Discord server, channel or DM - what was said, "
    "posted, decided, agreed or missed, who replied to whom, or to summarise, search, "
    "catch up on or export message history. Also use it when they name a channel with a "
    "leading hash. Read-only - it never posts, edits or reacts."
)

PROMPT = """\
Answer questions about my Discord with the `dexport` CLI. It drives my own
Discord desktop client, so treat it as strictly read-only.

- Find the channel first, unless I gave you an ID: `dexport guilds` lists my
  servers and `dexport channels -g "<server>"` lists a server's channels, both
  as `<id>  <name>` lines. Ask me instead of guessing if nothing matches.
- Read it with:
  `dexport export --channel-id <ID> -f json -o /tmp/dexport.json --limit 200`
  That writes the messages as JSON, oldest first — read the file and answer
  from it. Raise `--limit` if I ask about a longer stretch of history.
- Run one dexport command at a time, and never in a loop or on a timer.
- Never run `send`, `reply`, `react`, `edit` or `delete`. If I ask you to post
  something, write the message out and let me send it myself.
- If a command exits with `error: ...`, stop and show me that line. Do not
  re-run the command, and do not add `--restart`. If the error says Discord
  did not expose a CDP endpoint, my Discord client is still starting up:
  ask me to tell you when it has finished loading, then continue from where
  you left off.
"""


def _body(request: str) -> str:
    return f"{PROMPT}\n{request}\n"


def _claude(request: str) -> str:
    return (
        "---\n"
        f"description: {DESCRIPTION}\n"
        f"argument-hint: {ARGUMENT_HINT}\n"
        f"allowed-tools: {ALLOWED_TOOLS}\n"
        "---\n\n"
    ) + _body(request)


def _frontmatter_md(request: str) -> str:
    return f"---\ndescription: {DESCRIPTION}\n---\n\n" + _body(request)


def _hinted_md(request: str) -> str:
    return (f"---\ndescription: {DESCRIPTION}\nargument-hint: {ARGUMENT_HINT}\n---\n\n") + _body(
        request
    )


def _plain_md(request: str) -> str:
    return _body(request)


def _toml(request: str) -> str:
    return f'description = "{DESCRIPTION}"\n\nprompt = """\n{_body(request)}"""\n'


@dataclass(frozen=True)
class SkillSupport:
    """Where one agent keeps Agent Skills, and whether it reads ``allowed-tools``."""

    #: Skills directory, relative to ``$HOME``; the skill lands in ``<dir>/dexport/``.
    user_dir: str
    #: Skills directory, relative to a project root (``None`` = user-level only).
    project_dir: str | None
    #: Emit the :data:`ALLOWED_TOOLS` grant. The Agent Skills spec defines the
    #: field as *space*-separated and experimental; :data:`ALLOWED_TOOLS` is
    #: comma-separated, which only Claude Code accepts ("space- or
    #: comma-separated string, or a YAML list"). A space-delimited parser would
    #: read it as the tokens ``Bash(dexport`` / ``guilds:*),`` and grant
    #: whatever those happen to match, so everyone else is better off without.
    allowed_tools: bool = False


@dataclass(frozen=True)
class AgentTarget:
    """Where one agent keeps its slash commands, and in what shape."""

    key: str
    label: str
    #: Directory under ``$HOME`` whose presence means the agent is installed.
    marker: str
    #: Command file, relative to ``$HOME``.
    user_path: str
    #: Command file, relative to a project root (``None`` = user-level only).
    project_path: str | None
    #: How this agent injects the user's words; ``None`` = it appends them.
    argument_slot: str | None
    render: Callable[[str], str]
    #: Agent Skills support, if the agent has any.
    skill: SkillSupport | None = None


TARGETS: tuple[AgentTarget, ...] = (
    AgentTarget(
        key="claude",
        label="Claude Code",
        marker=".claude",
        user_path=".claude/commands/dexport.md",
        project_path=".claude/commands/dexport.md",
        argument_slot="$ARGUMENTS",
        render=_claude,
        skill=SkillSupport(
            user_dir=".claude/skills",
            project_dir=".claude/skills",
            allowed_tools=True,
        ),
    ),
    AgentTarget(
        key="codex",
        label="Codex CLI",
        marker=".codex",
        user_path=".codex/prompts/dexport.md",
        project_path=None,
        argument_slot="$ARGUMENTS",
        render=_plain_md,
        # Codex has no ``.codex/skills``: it reads the vendor-neutral
        # ``.agents/skills`` only -- at $HOME, at the repo root and at the cwd.
        # It is also the one target whose scopes differ between the two files,
        # since its prompts stay user-level.
        skill=SkillSupport(user_dir=".agents/skills", project_dir=".agents/skills"),
    ),
    AgentTarget(
        key="cursor",
        label="Cursor",
        marker=".cursor",
        user_path=".cursor/commands/dexport.md",
        project_path=".cursor/commands/dexport.md",
        argument_slot=None,
        render=_plain_md,
        skill=SkillSupport(user_dir=".cursor/skills", project_dir=".cursor/skills"),
    ),
    AgentTarget(
        key="gemini",
        label="Gemini CLI",
        marker=".gemini",
        user_path=".gemini/commands/dexport.toml",
        project_path=".gemini/commands/dexport.toml",
        argument_slot="{{args}}",
        render=_toml,
        skill=SkillSupport(user_dir=".gemini/skills", project_dir=".gemini/skills"),
    ),
    AgentTarget(
        key="opencode",
        label="opencode",
        marker=".config/opencode",
        user_path=".config/opencode/command/dexport.md",
        project_path=".opencode/command/dexport.md",
        argument_slot="$ARGUMENTS",
        render=_frontmatter_md,
        # opencode reads project skills from a bare ``.opencode/``, the same
        # split its commands already have.
        skill=SkillSupport(user_dir=".config/opencode/skills", project_dir=".opencode/skills"),
    ),
    AgentTarget(
        key="pi",
        label="pi",
        marker=".pi",
        # pi keeps its global config under ``~/.pi/agent`` but reads project
        # resources from a bare ``.pi/`` at the repo root, so the two scopes
        # are not the same suffix.
        user_path=".pi/agent/prompts/dexport.md",
        project_path=".pi/prompts/dexport.md",
        argument_slot="$ARGUMENTS",
        render=_hinted_md,
        skill=SkillSupport(user_dir=".pi/agent/skills", project_dir=".pi/skills"),
    ),
)

TARGETS_BY_KEY: dict[str, AgentTarget] = {t.key: t for t in TARGETS}


def render(target: AgentTarget | None = None) -> str:
    """The command file body for *target* (``None`` = a generic markdown one)."""
    if target is None:
        return _plain_md(_request("$ARGUMENTS"))
    return target.render(_request(target.argument_slot))


def _request(token: str | None) -> str:
    if token is None:
        # Nothing to interpolate: the agent appends whatever followed the slash
        # command to this prompt, so just point at it.
        return "\nMy request follows below."
    return f"\nMy request:\n\n{token}"


def render_skill(target: AgentTarget) -> str:
    """The ``SKILL.md`` body for *target*. No argument slot: a skill is loaded
    by the model off its own description, not invoked with the user's words."""
    head = f"---\nname: {NAME}\ndescription: {SKILL_DESCRIPTION}\n"
    if target.skill is not None and target.skill.allowed_tools:
        head += f"allowed-tools: {ALLOWED_TOOLS}\n"
    return f"{head}---\n\n{PROMPT}"


def target_path(target: AgentTarget, *, home: Path, root: Path | None = None) -> Path | None:
    """Absolute path of the command file; ``None`` if *root* is given (project
    scope) but this agent has no project-level command directory."""
    if root is None:
        return home / target.user_path
    if target.project_path is None:
        return None
    return root / target.project_path


def skill_path(target: AgentTarget, *, home: Path, root: Path | None = None) -> Path | None:
    """Absolute path of the ``SKILL.md``; ``None`` if this agent has no skills,
    or none at the requested scope."""
    if target.skill is None:
        return None
    if root is None:
        return home / target.skill.user_dir / NAME / "SKILL.md"
    if target.skill.project_dir is None:
        return None
    return root / target.skill.project_dir / NAME / "SKILL.md"


def detect(home: Path) -> list[AgentTarget]:
    """Targets whose config directory exists under *home*."""
    return [t for t in TARGETS if (home / t.marker).is_dir()]


def write(path: Path, text: str, *, force: bool = False) -> bool:
    """Write the command file. Returns ``False`` if it exists and *force* is off."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True
