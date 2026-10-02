"""Turn a Telegram Bot API update (as JSON) into an `Incoming` message."""

from datetime import datetime, timezone

from budget.incoming import Incoming, is_receipt_mime


def _utc(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _full_name(user: dict) -> str:
    return " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p)


def _largest_photo(sizes: list[dict]) -> dict:
    return max(sizes, key=lambda s: (s.get("width", 0) * s.get("height", 0), s.get("file_size", 0)))


def _author(message: dict) -> tuple[int | None, str | None, datetime, bool]:
    """Original author id, name, original date, and whether it was forwarded."""
    origin = message.get("forward_origin")
    if origin is None:
        user = message.get("from") or {}
        return user.get("id"), _full_name(user) or None, _utc(message["date"]), False
    date = _utc(origin["date"])
    kind = origin.get("type")
    if kind == "user":
        user = origin["sender_user"]
        return user["id"], _full_name(user) or None, date, True
    if kind == "hidden_user":
        return None, origin.get("sender_user_name"), date, True
    # "chat" / "channel": forwarded from a group or channel, no person behind it.
    chat = origin.get("sender_chat") or origin.get("chat") or {}
    return None, origin.get("author_signature") or chat.get("title"), date, True


def parse_update(update: dict) -> Incoming | None:
    """Return the message carried by the update, or None if there is nothing to log.

    Only new messages count; edits, callbacks and other update types are skipped.
    Photos and PDF/image documents are always returned; text is returned as is
    and left to the caller to parse as an amount.
    """
    message = update.get("message")
    if not message:
        return None
    author_id, author_name, date, forwarded = _author(message)
    common = dict(
        source="telegram",
        chat_id=(message.get("chat") or {}).get("id"),
        message_id=message["message_id"],
        original_date=date,
        author_user_id=author_id,
        author_name=author_name,
        sender_user_id=(message.get("from") or {}).get("id"),
        forwarded=forwarded,
        media_group_id=message.get("media_group_id"),
    )
    if message.get("photo"):
        photo = _largest_photo(message["photo"])
        return Incoming(kind="photo", text=message.get("caption"),
                        file_id=photo["file_id"], file_unique_id=photo["file_unique_id"],
                        **common)
    if document := message.get("document"):
        mime = document.get("mime_type")
        if not is_receipt_mime(mime):
            return None
        return Incoming(kind="document", text=message.get("caption"),
                        file_id=document["file_id"], file_unique_id=document["file_unique_id"],
                        file_name=document.get("file_name"), mime_type=mime, **common)
    if message.get("text"):
        return Incoming(kind="text", text=message["text"], **common)
    return None
