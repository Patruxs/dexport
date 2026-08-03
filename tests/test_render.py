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


def test_json_keeps_raw_objects_and_unicode():
    text = to_json(MESSAGES)
    assert "👍" in text  # not \\u-escaped
    assert json.loads(text)[1] == MESSAGES[0]


# --------------------------------------------------------------------------
# Terminal
# --------------------------------------------------------------------------


def test_terminal_title_rule():
    first_line = _render(MESSAGES, title="Room").splitlines()[0]
    assert "Room" in first_line
    assert "─" in first_line


def test_terminal_without_title_has_no_rule():
    assert "─" not in _render(MESSAGES)


def test_terminal_is_chronological():
    out = _render(MESSAGES)
    assert out.index("first") < out.index("second")


def test_terminal_shows_author_and_timestamp():
    out = _render(MESSAGES)
    assert "Bob 2024-01-01 12:05" in out
    assert "alice 2024-01-01 12:00" in out


def test_terminal_marks_edited_messages_only():
    assert "(edited)" in _render([EDITED])
    assert "(edited)" not in _render(MESSAGES)


def test_terminal_attachment_line_includes_human_size():
    assert "📎 a.png (2.0KB): http://x/a.png" in _render(MESSAGES)


def test_terminal_reaction_summary():
    assert "👍x3" in _render(MESSAGES)


def test_terminal_empty_list_prints_placeholder():
    out = _render([], title="Room")
    assert "(no messages)" in out
    assert "Room" in out


def test_terminal_attachment_only_message():
    msg = {
        "id": "3",
        "author": {"username": "carl"},
        "content": "",
        "timestamp": None,
        "attachments": [{"filename": "f.txt", "url": "http://x/f.txt"}],
    }
    out = _render([msg])
    assert "carl" in out
    assert "📎 f.txt: http://x/f.txt" in out


# --------------------------------------------------------------------------
# export_to_file / exporters registry
# --------------------------------------------------------------------------


def test_export_markdown_file(tmp_path):
    path = tmp_path / "out.md"
    assert export_to_file(MESSAGES, str(path), "md", title="Room") == 2
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Room\n")
    assert text.index("first") < text.index("second")
    assert text == to_markdown(MESSAGES, title="Room")


def test_export_json_file(tmp_path):
    path = tmp_path / "out.json"
    assert export_to_file(MESSAGES, str(path), "json") == 2
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [m["id"] for m in data] == ["1", "2"]
    assert data[1] == MESSAGES[0]


@pytest.mark.parametrize("fmt", ["MD", "Markdown", "mArKdOwN", "JSON"])
def test_export_format_is_case_insensitive(tmp_path, fmt):
    path = tmp_path / "out"
    export_to_file(MESSAGES, str(path), fmt, title="Room")
    expected = get_exporter(fmt.lower())(MESSAGES, "Room")
    assert path.read_text(encoding="utf-8") == expected


def test_export_unknown_format_raises_and_writes_nothing(tmp_path):
    path = tmp_path / "out.xml"
    with pytest.raises(ValueError, match="'xml'"):
        export_to_file(MESSAGES, str(path), "xml")
    assert not path.exists()


def test_export_empty_list_returns_zero(tmp_path):
    path = tmp_path / "empty.md"
    assert export_to_file([], str(path), "md") == 0
    assert "_Exported 0 messages._" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fmt", "func"),
    [("md", to_markdown), ("markdown", to_markdown), ("json", to_json), ("JSON", to_json)],
)
def test_get_exporter(fmt, func):
    assert get_exporter(fmt) is func


def test_get_exporter_unknown_lists_known_formats():
    with pytest.raises(ValueError, match=r"'nope'.*json.*markdown.*md"):
        get_exporter("nope")


def test_every_exporter_has_an_extension():
    assert set(EXPORTERS) <= set(EXPORT_EXTENSIONS)


@pytest.mark.parametrize("fmt", sorted(EXPORTERS))
def test_every_registered_format_exports(tmp_path, fmt):
    path = tmp_path / f"out.{EXPORT_EXTENSIONS[fmt]}"
    assert export_to_file(MESSAGES, str(path), fmt, title="Room") == 2
    assert path.stat().st_size > 0


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        ("2024-01-01T12:05:00Z", "2024-01-01 12:05"),
        ("2024-01-01T12:05:00+00:00", "2024-01-01 12:05"),
        ("2024-01-01T12:05:00.123000+00:00", "2024-01-01 12:05"),
        ("not a date", "not a date"),
        ("", ""),
        (None, ""),
    ],
)
def test_format_timestamp(iso, expected):
    assert format_timestamp(iso) == expected


@pytest.mark.parametrize(
    ("author", "expected"),
    [
        ({"global_name": "Bob", "username": "bob", "id": "1"}, "Bob"),
        ({"global_name": None, "username": "alice", "id": "1"}, "alice"),
        ({"global_name": "", "username": "alice"}, "alice"),
        ({"id": "42"}, "42"),
        ({}, "unknown"),
        (None, "unknown"),
    ],
)
def test_display_name_fallbacks(author, expected):
    assert display_name(author) == expected


def test_summarize_author():
    assert summarize_author({"username": "alice", "global_name": "Alice"}) == "Alice (@alice)"
    assert summarize_author({"username": "bob"}) == "@bob"


def test_summarize_author_collapses_identical_names():
    assert summarize_author({"username": "bob", "global_name": "bob"}) == "@bob"


def test_summarize_author_without_username_uses_display_name():
    assert summarize_author({"id": "42"}) == "42"


def test_attachment_lines_omit_size_when_unknown():
    msg = {"attachments": [{"filename": "a.bin", "url": "u"}, {"url": "v", "size": "big"}]}
    assert attachment_lines(msg) == ["a.bin: u", "file: v"]
