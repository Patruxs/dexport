"""The ``install-agent`` command: drop a ``/dexport`` slash command into
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
    """Install the /dexport slash command for your coding agent(s)."""
    picked = _validated(target)
    if show:
        # Raw echo, not console.print: this is meant to be piped into a file,
        # so it must not be wrapped to the terminal width or read as markup.
        typer.echo(agents.render(picked[0] if len(picked) == 1 else None))
        return

    root = Path.cwd() if project else None
    written = 0
    for agent in picked or _detected():
        path = agents.target_path(agent, home=Path.home(), root=root)
        if path is None:
            console.print(f"[yellow]skipped[/yellow] {agent.label}: no project-level commands")
            continue
        if agents.write(path, agents.render(agent), force=force):
            console.print(f"[green]installed[/green] {agent.label}  [dim]{path}[/dim]")
            written += 1
        else:
            console.print(f"[yellow]exists[/yellow] {agent.label}  [dim]{path}[/dim] (--force)")
    if written:
        console.print("\nRestart your agent if it was open, then try: [bold]/dexport[/bold] ...")


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
