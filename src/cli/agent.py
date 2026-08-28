"""The ``install-agent`` command: drop a ``/dexport`` slash command -- and,
where the agent supports Agent Skills, a model-discoverable ``SKILL.md`` -- into
whatever coding agents are installed."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .. import agents
from .common import console, fail

commands = typer.Typer()

_KEYS = ", ".join(t.key for t in agents.TARGETS)


@commands.command()
def install_agent(
    target: Annotated[
        list[str] | None,
        typer.Option("--target", "-t", help=f"Agent to install for ({_KEYS}); repeatable."),
    ] = None,
    project: Annotated[
        bool, typer.Option("--project", help="Install into ./ instead of your home directory.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing command.")] = False,
    show: Annotated[
        bool, typer.Option("--print", help="Print the command text, install nothing.")
    ] = False,
) -> None:
    """Install the /dexport command (and skill) for your coding agent(s)."""
    picked = _validated(target)
    if show:
        # Raw echo, not console.print: this is meant to be piped into a file,
        # so it must not be wrapped to the terminal width or read as markup.
        typer.echo(agents.render(picked[0] if len(picked) == 1 else None))
        return

    home, root = Path.home(), Path.cwd() if project else None
    written = 0
    skilled = False
    for agent in picked or _detected():
        # The two files are placed independently: Codex takes a project-level
        # skill but keeps its prompts user-level, so one being out of scope
        # must not skip the other.
        command = agents.target_path(agent, home=home, root=root)
        skill = agents.skill_path(agent, home=home, root=root)
        if command is None and skill is None:
            console.print(f"[yellow]skipped[/yellow] {agent.label}: nothing at project level")
            continue
        if command is not None:
            written += _write(f"{agent.label} command", command, agents.render(agent), force=force)
        if skill is not None:
            written += _write(
                f"{agent.label} skill", skill, agents.render_skill(agent), force=force
            )
            skilled = True
    if written:
        console.print("\nRestart your agent if it was open.")
        if skilled:
            # The skill is the whole point of asking in plain words: it is the
            # only copy the model loads without being told to.
            console.print("Then just ask about your Discord in plain language.")
        console.print("Either way, [bold]/dexport[/bold] ... always works.")


def _write(label: str, path: Path, text: str, *, force: bool) -> int:
    """Write one file, report it, and return how many were actually written."""
    if agents.write(path, text, force=force):
        console.print(f"[green]installed[/green] {label}  [dim]{path}[/dim]")
        return 1
    console.print(f"[yellow]exists[/yellow] {label}  [dim]{path}[/dim] (--force)")
    return 0


def _validated(target: list[str] | None) -> list[agents.AgentTarget]:
    """The ``--target`` keys as targets, de-duplicated; empty if none were given."""
    if not target:
        return []
    unknown = [k for k in target if k not in agents.TARGETS_BY_KEY]
    if unknown:
        fail(f"Unknown agent(s): {', '.join(unknown)}. Known: {_KEYS}.")
    return [agents.TARGETS_BY_KEY[k] for k in dict.fromkeys(target)]


def _detected() -> list[agents.AgentTarget]:
    """Every agent found in the home directory, or a helpful failure."""
    found = agents.detect(Path.home())
    if not found:
        fail(
            f"No coding agent detected. Pass --target ({_KEYS}), or use --print "
            "and paste the text wherever your agent keeps its prompts."
        )
    return found
