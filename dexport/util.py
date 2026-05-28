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
