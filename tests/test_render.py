"""Tests for :mod:`dexport.render` — terminal output, file export, helpers.

Terminal output is captured through a :class:`rich.console.Console` writing to
a ``StringIO`` with colour disabled, so assertions see plain text.
"""

import io
import json

import pytest
from rich.console import Console

from dexport.render import (
    EXPORT_EXTENSIONS,
    EXPORTERS,
    attachment_lines,
    display_name,
    export_to_file,
    format_timestamp,
    get_exporter,
    oldest_first,
    reaction_summary,
    render_terminal,
    summarize_author,
    to_json,
    to_markdown,
)

# Discord returns newest-first; index 0 is the most recent message.
MESSAGES = [
    {
        "id": "2",
        "author": {"username": "bob", "global_name": "Bob"},
        "content": "second",
        "timestamp": "2024-01-01T12:05:00+00:00",
        "reactions": [{"emoji": {"name": "👍"}, "count": 3}],
    },
    {
        "id": "1",
        "author": {"username": "alice", "global_name": None},
        "content": "first",
        "timestamp": "2024-01-01T12:00:00+00:00",
        "attachments": [{"filename": "a.png", "url": "http://x/a.png", "size": 2048}],
    },
]

EDITED = {**MESSAGES[0], "edited_timestamp": "2024-01-01T12:06:00+00:00"}


def _render(messages, title=None) -> str:
    console = Console(file=io.StringIO(), force_terminal=False, width=200, no_color=True)
    render_terminal(messages, title=title, console=console)
    return console.file.getvalue()


# --------------------------------------------------------------------------
# Markdown / JSON
# --------------------------------------------------------------------------


def test_markdown_is_chronological():
    md = to_markdown(MESSAGES, title="Room")
    assert md.index("first") < md.index("second")
    assert "# Room" in md
    assert "📎 a.png" in md
    assert "👍x3" in md


def test_markdown_marks_edited_messages_only():
    assert "*(edited)*" in to_markdown([EDITED])
    assert "(edited)" not in to_markdown(MESSAGES)


def test_markdown_without_title_has_no_heading():
    md = to_markdown(MESSAGES)
    assert not md.startswith("#")
    assert "_Exported 2 messages._" in md


def test_json_is_chronological():
    data = json.loads(to_json(MESSAGES))
    assert [m["id"] for m in data] == ["1", "2"]
