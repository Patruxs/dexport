"""The Typer application and its root callback (global connection options)."""

from __future__ import annotations

import typer

from .. import __version__
from ..config import DEFAULT_CDP_PORT
from .common import ConnectionOptions

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Drive your own Discord session from the CLI (attaches to the desktop "
        "client over CDP).\n\n"
        "WARNING: automating a user account is against Discord's Terms of "
        "Service and is punished with permanent account termination. Intended "
        "for personal, low-volume use on your own account and data. Use at "
        "your own risk."
    ),
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"dexport {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    port: int | None = typer.Option(
        None,
        "--port",
        help=f"CDP port Discord exposes (default from config, else {DEFAULT_CDP_PORT}).",
    ),
    restart: bool = typer.Option(
        False, "--restart", help="Kill and relaunch Discord if it isn't debuggable yet."
    ),
    binary: str | None = typer.Option(
        None, "--binary", help="Path to the Discord executable (override auto-detect)."
    ),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    # Commands read these back via ``connect(ctx)``; nothing is touched on
    # disk until a command actually needs Discord.
    ctx.obj = ConnectionOptions(port=port, restart=restart, binary=binary)
