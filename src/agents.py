"""The ``/dexport`` slash command, rendered for each coding agent.

One prompt (:data:`PROMPT`), several wrappers: every agent keeps its commands
in a different place and spells "the rest of what the user typed" differently.
:func:`render` produces the file body for a target, :func:`target_path` says
where it goes, and ``dexport install-agent`` writes it. Anything not listed in
:data:`TARGETS` is served by ``--print``.

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

#: Claude Code tool allowlist — read verbs only, so a prompt injected into a
#: channel cannot talk the agent into posting anything.
ALLOWED_TOOLS = "Bash(dexport guilds:*), Bash(dexport channels:*), Bash(dexport export:*), Read"

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
- If a command exits with `error: ...`, show me that line instead of retrying.
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


def _plain_md(request: str) -> str:
    return _body(request)


def _toml(request: str) -> str:
    return f'description = "{DESCRIPTION}"\n\nprompt = """\n{_body(request)}"""\n'


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


TARGETS: tuple[AgentTarget, ...] = (
    AgentTarget(
        key="claude",
        label="Claude Code",
        marker=".claude",
        user_path=".claude/commands/dexport.md",
        project_path=".claude/commands/dexport.md",
        argument_slot="$ARGUMENTS",
        render=_claude,
    ),
    AgentTarget(
        key="codex",
        label="Codex CLI",
        marker=".codex",
        user_path=".codex/prompts/dexport.md",
        project_path=None,
        argument_slot="$ARGUMENTS",
        render=_plain_md,
    ),
    AgentTarget(
        key="cursor",
        label="Cursor",
        marker=".cursor",
        user_path=".cursor/commands/dexport.md",
        project_path=".cursor/commands/dexport.md",
        argument_slot=None,
        render=_plain_md,
    ),
    AgentTarget(
        key="gemini",
        label="Gemini CLI",
        marker=".gemini",
        user_path=".gemini/commands/dexport.toml",
        project_path=".gemini/commands/dexport.toml",
        argument_slot="{{args}}",
        render=_toml,
    ),
    AgentTarget(
        key="opencode",
        label="opencode",
        marker=".config/opencode",
        user_path=".config/opencode/command/dexport.md",
        project_path=".opencode/command/dexport.md",
        argument_slot="$ARGUMENTS",
        render=_frontmatter_md,
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


def target_path(target: AgentTarget, *, home: Path, root: Path | None = None) -> Path | None:
    """Absolute path of the command file; ``None`` if *root* is given (project
    scope) but this agent has no project-level command directory."""
    if root is None:
        return home / target.user_path
    if target.project_path is None:
        return None
    return root / target.project_path


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
