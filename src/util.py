"""Small pure helpers shared across modules.

Kept dependency-free (stdlib only) so it is trivially unit-testable and cheap
to import.
"""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")


def strip_diacritics(text: str) -> str:
    """Remove combining marks, turning ``"lười"`` into ``"luoi"``.

    Vietnamese ``đ``/``Đ`` decompose oddly under NFKD, so they are handled
    explicitly before the generic combining-mark strip.
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str | None) -> str:
    """Casefold, strip diacritics, and collapse whitespace for fuzzy matching."""
    if text is None:
        return ""
    folded = strip_diacritics(text).casefold()
    return _WS_RE.sub(" ", folded).strip()


def is_snowflake(value: str) -> bool:
    """True when ``value`` looks like a Discord snowflake ID.

    Real snowflakes are 17-19 digits (20 leaves headroom). The tight bound
    keeps an all-numeric channel/guild *name* from being misread as an ID.
    """
    return bool(value) and value.isdigit() and 17 <= len(value) <= 20


def human_bytes(size: int) -> str:
    """``512B`` / ``1.5KB`` / ``5.0MB`` ... (last unit is TB, never overflows)."""
    step = 1024.0
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(size)
    for unit in units:
        if val < step or unit == units[-1]:
            return f"{val:.0f}{unit}" if unit == "B" else f"{val:.1f}{unit}"
        val /= step
    raise AssertionError("unreachable")  # pragma: no cover
