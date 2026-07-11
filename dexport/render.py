"""Terminal rendering and file export for message lists.

Discord returns messages newest-first; every function here takes that raw list
and presents it oldest-first, which is how a human reads a conversation.

To add an export format, write a ``(messages, title) -> str`` function and add
it to :data:`EXPORTERS`; ``export_to_file`` and the CLI pick it up from there.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from rich.console import Console

from .models import Message
from .util import human_bytes

# --------------------------------------------------------------------------
# Shared formatting helpers
# --------------------------------------------------------------------------


def display_name(author: dict[str, Any] | None) -> str:
    """Best human-readable name for a Discord user object."""
    if not author:
        return "unknown"
    name: str = author.get("global_name") or author.get("username") or author.get("id", "unknown")
    return name


def summarize_author(author: dict[str, Any]) -> str:
    """``Display Name (@username)``, or just ``@username`` when they coincide."""
    name = display_name(author)
    username = author.get("username")
    if username and username != name:
        return f"{name} (@{username})"
    return f"@{username}" if username else name


def format_timestamp(iso: str | None) -> str:
    """``YYYY-MM-DD HH:MM`` from a Discord ISO timestamp (unparseable → as-is)."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso


def attachment_lines(msg: Message) -> list[str]:
    out = []
    for att in msg.get("attachments", []) or []:
        size = att.get("size")
        suffix = f" ({human_bytes(size)})" if isinstance(size, int) else ""
        out.append(f"{att.get('filename', 'file')}{suffix}: {att.get('url', '')}")
    return out


def reaction_summary(msg: Message) -> str:
    parts = []
    for r in msg.get("reactions", []) or []:
        emoji = (r.get("emoji") or {}).get("name") or "?"
        parts.append(f"{emoji}x{r.get('count', 0)}")
    return "  ".join(parts)


def oldest_first(messages: Iterable[Message]) -> list[Message]:
    """Discord orders newest-first; reverse to chronological."""
    return list(reversed(list(messages)))


# --------------------------------------------------------------------------
# Terminal
# --------------------------------------------------------------------------


def render_terminal(
    messages: list[Message],
    *,
    title: str | None = None,
    console: Console | None = None,
) -> None:
    """Pretty-print ``messages`` oldest-first (to ``console`` or stdout)."""
    console = console or Console()
    ordered = oldest_first(messages)
    if title:
        console.rule(f"[bold]{title}[/bold]")
    if not ordered:
        console.print("[dim](no messages)[/dim]")
        return
    for msg in ordered:
        name = display_name(msg.get("author"))
        ts = format_timestamp(msg.get("timestamp"))
        edited = " (edited)" if msg.get("edited_timestamp") else ""
        console.print(f"[bold cyan]{name}[/bold cyan] [dim]{ts}{edited}[/dim]")
        content = msg.get("content") or ""
        if content:
            console.print(content)
        for line in attachment_lines(msg):
            console.print(f"  [magenta]📎 {line}[/magenta]")
        reactions = reaction_summary(msg)
        if reactions:
            console.print(f"  [yellow]{reactions}[/yellow]")
        console.print()


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def to_markdown(messages: list[Message], title: str | None = None) -> str:
    ordered = oldest_first(messages)
    lines: list[str] = []
    if title:
        lines.append(f"# {title}")
        lines.append("")
    lines.append(f"_Exported {len(ordered)} messages._")
    lines.append("")
    for msg in ordered:
        name = display_name(msg.get("author"))
        ts = format_timestamp(msg.get("timestamp"))
        edited = " *(edited)*" if msg.get("edited_timestamp") else ""
        lines.append(f"### {name} — {ts}{edited}")
        content = msg.get("content") or ""
        if content:
            lines.append("")
            lines.append(content)
        atts = attachment_lines(msg)
        if atts:
            lines.append("")
            for line in atts:
                lines.append(f"- 📎 {line}")
        reactions = reaction_summary(msg)
        if reactions:
            lines.append("")
            lines.append(f"> {reactions}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_json(messages: list[Message], title: str | None = None) -> str:
    """Raw message objects as a JSON array, oldest first (``title`` unused)."""
    return json.dumps(oldest_first(messages), ensure_ascii=False, indent=2)


#: Export format name -> renderer. Keys are matched case-insensitively.
Exporter = Callable[[list[Message], str | None], str]
EXPORTERS: dict[str, Exporter] = {
    "md": to_markdown,
    "markdown": to_markdown,
    "json": to_json,
}

#: Format name -> file extension used for default output paths.
EXPORT_EXTENSIONS: dict[str, str] = {"md": "md", "markdown": "md", "json": "json"}


def get_exporter(fmt: str) -> Exporter:
    try:
        return EXPORTERS[fmt.lower()]
    except KeyError:
        known = ", ".join(sorted(set(EXPORTERS)))
        raise ValueError(f"Unknown export format: {fmt!r} (use one of: {known})") from None


def export_to_file(
    messages: list[Message],
    path: str,
    fmt: str,
    *,
    title: str | None = None,
) -> int:
    """Write messages to ``path`` in ``fmt`` (see :data:`EXPORTERS`). Returns count."""
    text = get_exporter(fmt)(messages, title)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return len(messages)
