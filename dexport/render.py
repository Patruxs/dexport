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
