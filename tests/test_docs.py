"""Guards against documentation drift.

README.md must keep tracking the code: every source module in the "Project
layout" table, every ``Settings`` field in the Configuration table, every CLI
command in the "Command reference" table, and a console-script entry point
that really resolves to the Typer app.
"""

from __future__ import annotations

import dataclasses
import importlib
import re
import tomllib
from pathlib import Path

import pytest
import typer

from dexport.cli import app
from dexport.config import ENV_DISCORD_BINARY, ENV_HOME, ENV_PORT, Settings

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
PACKAGE = ROOT / "dexport"

# Package plumbing that is not a documented "module".
SKIP_STEMS = {"__init__", "__main__"}


# --------------------------------------------------------------------------
# README helpers
# --------------------------------------------------------------------------


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """Body of the ``heading`` section at any level, up to the next heading
    of the same or a higher level."""
    m = re.search(rf"^(#+) {re.escape(heading)}\s*$", text, re.MULTILINE)
    assert m, f"README is missing a '{heading}' heading"
    level = len(m.group(1))
    nxt = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE).search(text, m.end())
    return text[m.end() : nxt.start() if nxt else len(text)]


def _backticked(text: str) -> set[str]:
    return set(re.findall(r"`([^`\n]+)`", text))


def _first_column(section: str) -> set[str]:
    """Backticked token from the first cell of every markdown table row."""
    out: set[str] = set()
    for line in section.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        first = line.strip().strip("|").split("|")[0].strip()
        m = re.fullmatch(r"`([^`]+)`", first)
        if m:
            out.add(m.group(1))
    return out


def _code_blocks(text: str) -> list[str]:
    return re.findall(r"^```[^\n]*\n(.*?)^```", text, re.MULTILINE | re.DOTALL)


# --------------------------------------------------------------------------
# Source-of-truth helpers
# --------------------------------------------------------------------------


def _source_modules() -> dict[str, set[str]]:
    """``{"cli/read.py": {names the README may use to list it}}``.

    A module inside a sub-package is satisfied by its own file name or by the
    package directory (``cli/`` / ``cli``).
    """
    modules: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or path.stem in SKIP_STEMS:
            continue
        rel = path.relative_to(PACKAGE)
        names = {rel.name, rel.as_posix()}
        if len(rel.parts) > 1:
            pkg = rel.parts[0]
            names |= {pkg, f"{pkg}/"}
        modules[rel.as_posix()] = names
    return modules


def _module_exists(token: str) -> bool:
    """Does a README "Module" cell like ``api.py`` or ``cli/`` exist on disk?"""
    candidate = PACKAGE / token.rstrip("/")
    if token.endswith("/"):
        return candidate.is_dir()
    if token.endswith(".py"):
        return candidate.is_file()
    return candidate.is_dir() or candidate.with_suffix(".py").is_file()


def _registered_commands(root: typer.Typer) -> set[str]:
    infos = list(root.registered_commands)
    for group in root.registered_groups:
        infos.extend(group.typer_instance.registered_commands)
    # Typer derives the CLI name from the function name when ``name`` is unset.
    return {(info.name or info.callback.__name__).lower().replace("_", "-") for info in infos}


# --------------------------------------------------------------------------
# Sanity: the helpers must actually find things, or the tests below could
# pass vacuously.
# --------------------------------------------------------------------------


def test_source_modules_discovered():
    modules = _source_modules()
    assert "api.py" in modules
    assert "cli/read.py" in modules
    assert "launcher/discovery.py" in modules
    assert not any(name.startswith("__") for name in modules)


def test_registered_commands_discovered():
    assert {"whoami", "send", "configure"} <= _registered_commands(app)


# --------------------------------------------------------------------------
# (1) Project layout
# --------------------------------------------------------------------------


def test_readme_project_layout_lists_every_module():
    listed = _backticked(_section(_readme(), "Project layout"))
    missing = sorted(mod for mod, names in _source_modules().items() if not names & listed)
    assert not missing, f"README 'Project layout' does not mention: {missing}"


def test_readme_project_layout_has_no_stale_modules():
    tokens = _first_column(_section(_readme(), "Project layout"))
    assert tokens, "README 'Project layout' table has no module rows"
    stale = sorted(t for t in tokens if not _module_exists(t))
    assert not stale, f"README 'Project layout' lists modules that do not exist: {stale}"


# --------------------------------------------------------------------------
# (2) Configuration
# --------------------------------------------------------------------------


def test_readme_configuration_documents_every_settings_field():
    documented = _backticked(_section(_readme(), "Configuration"))
    missing = [f.name for f in dataclasses.fields(Settings) if f.name not in documented]
    assert not missing, f"README 'Configuration' does not document Settings fields: {missing}"


def test_readme_configuration_has_no_stale_keys():
    keys = _first_column(_section(_readme(), "Configuration"))
    assert keys, "README 'Configuration' table has no key rows"
    fields = {f.name for f in dataclasses.fields(Settings)}
    stale = sorted(keys - fields)
    assert not stale, f"README 'Configuration' lists keys Settings does not have: {stale}"
