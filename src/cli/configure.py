"""The ``configure`` command: view or update ``config.json``."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from ..config import Paths, Settings
from .common import console

commands = typer.Typer()


@commands.command()
def configure(
    port: Annotated[int | None, typer.Option("--port", help="Set the default CDP port.")] = None,
    binary: Annotated[
        str | None, typer.Option("--binary", help="Set the Discord binary path.")
    ] = None,
    show: Annotated[bool, typer.Option("--show", help="Print the current config.")] = False,
) -> None:
    """View or update ~/.dexport/config.json."""
    paths = Paths.default()
    # Base off the on-disk file (not the env-merged settings) so environment
    # overrides like DEXPORT_PORT are never persisted unintentionally.
    settings = Settings.load_file(paths)
    changed = False
    if port is not None:
        settings.port = port
        changed = True
    if binary is not None:
        settings.discord_binary = binary
        changed = True
    if changed:
        settings.save(paths)
        console.print("[green]Saved[/green] config.")
    if show or not changed:
        console.print(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2))
        console.print(f"[dim]config: {paths.config}[/dim]")
