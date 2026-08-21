"""dexport command-line interface (Typer).

Connection options are global and come *before* the sub-command::

    dexport --port 9222 read -g "cú đêm" -c "lười-chat-tổng" --limit 100

Commands live in one module per group; each module exposes a ``commands``
Typer that is merged into the root :data:`app` here. The order below is the
order they appear in ``dexport --help``.

Shared plumbing (console, error handling, target resolution, the write-verb
runner) is in :mod:`.common`.
"""

from __future__ import annotations

from . import configure, read, write
from .app import app

# whoami / guilds / channels / read / export — never modify anything.
app.add_typer(read.commands)
# send / reply / react / edit / delete — confirm, --dry-run, human pause.
app.add_typer(write.commands)
# configure — view/update config.json.
app.add_typer(configure.commands)

__all__ = ["app"]
