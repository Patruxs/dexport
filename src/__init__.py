"""dexport — drive your own Discord session from the CLI.

dexport attaches to the *already-running* Discord desktop client over the
Chrome DevTools Protocol, snapshots the client's real request headers once,
and then issues Discord API calls with an in-page ``fetch``. Reusing the live
headers is what keeps requests well-formed as Discord's client build changes,
without dexport having to reconstruct the build-specific header cluster.

The public entry point is the Typer app in :mod:`dexport.cli`.
"""

__version__ = "0.2.0"
