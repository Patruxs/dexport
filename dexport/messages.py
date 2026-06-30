"""Discord *message* endpoints: history, send/reply, edit, delete, react.

This is the only module that knows the message URL layout. Each write
operation is exposed as a **request builder** returning an
:class:`~dexport.api.ApiRequest`; the caller decides whether to preview it
(``--dry-run``) or send it via :meth:`ApiCore.execute`. That keeps the preview
and the real request from ever drifting apart.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote

from .api import ApiCore, ApiRequest
from .models import Message

#: Discord caps ``GET /channels/{id}/messages`` at 100 per page.
MAX_PAGE_SIZE = 100

_CUSTOM_EMOJI_RE = re.compile(r"^<a?:([A-Za-z0-9_]+):(\d+)>$")


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------


def history_request(channel_id: str, *, limit: int, before: str | None = None) -> ApiRequest:
    path = f"/channels/{channel_id}/messages?limit={limit}"
    if before:
        path += f"&before={before}"
    return ApiRequest("GET", path)


def fetch_history(
    api: ApiCore,
    channel_id: str,
    limit: int = MAX_PAGE_SIZE,
    *,
    before: str | None = None,
    on_page: Callable[[int], None] | None = None,
) -> list[Message]:
    """Return up to ``limit`` messages, newest first (Discord's order).

    Pages through ``?limit=100&before=`` until enough are collected or the
    channel runs out. ``on_page`` is called with the running total after each
    page so callers can show progress.
    """
    collected: list[Message] = []
    cursor = before
    while len(collected) < limit:
        page_size = min(MAX_PAGE_SIZE, limit - len(collected))
        batch: list[Message] = (
            api.execute(history_request(channel_id, limit=page_size, before=cursor)).json() or []
        )
        if not batch:
            break
        collected.extend(batch)
        if on_page:
            on_page(len(collected))
        if len(batch) < page_size:
            break
        cursor = batch[-1]["id"]
    return collected[:limit]


# --------------------------------------------------------------------------
# Write — request builders
# --------------------------------------------------------------------------


def send_message_request(
    channel_id: str,
    content: str,
    *,
    reply_to: str | None = None,
    fail_if_not_exists: bool = False,
) -> ApiRequest:
    """``POST`` a message; with ``reply_to`` it becomes a reply."""
    body: dict[str, object] = {"content": content}
    if reply_to:
        body["message_reference"] = {
            "channel_id": channel_id,
            "message_id": reply_to,
            "fail_if_not_exists": fail_if_not_exists,
        }
    return ApiRequest("POST", f"/channels/{channel_id}/messages", body)


def edit_message_request(channel_id: str, message_id: str, content: str) -> ApiRequest:
    return ApiRequest(
        "PATCH", f"/channels/{channel_id}/messages/{message_id}", {"content": content}
    )


def delete_message_request(channel_id: str, message_id: str) -> ApiRequest:
    return ApiRequest("DELETE", f"/channels/{channel_id}/messages/{message_id}")


def add_reaction_request(channel_id: str, message_id: str, emoji: str) -> ApiRequest:
    return ApiRequest("PUT", _reaction_path(channel_id, message_id, emoji))


def remove_reaction_request(channel_id: str, message_id: str, emoji: str) -> ApiRequest:
    return ApiRequest("DELETE", _reaction_path(channel_id, message_id, emoji))
