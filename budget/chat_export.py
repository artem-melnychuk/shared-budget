"""Read a Telegram Desktop chat export (`result.json`, JSON format)."""

import json
import mimetypes
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from budget.incoming import Incoming, is_receipt_mime

# Old exports without `date_unixtime` give local wall-clock time.
DEFAULT_TZ = "Europe/Paris"


def flatten_text(text) -> str:
    """`text` is a string, or a list of strings and entity objects with a `text` key."""
    if isinstance(text, str):
        return text
    return "".join(part if isinstance(part, str) else part.get("text", "") for part in text or [])


def _date(entry: dict, tz: ZoneInfo) -> datetime:
    if entry.get("date_unixtime"):
        return datetime.fromtimestamp(int(entry["date_unixtime"]), tz=timezone.utc)
    local = datetime.fromisoformat(entry["date"])
    return local.replace(tzinfo=tz).astimezone(timezone.utc)


def _user_id(from_id) -> int | None:
    if isinstance(from_id, str) and from_id.startswith("user") and from_id[4:].isdigit():
        return int(from_id[4:])
    return None


def _exported(path) -> bool:
    # Media left out of the export reads "(File not included. ...)".
    return isinstance(path, str) and not path.startswith("(")


def parse_export(data: dict, tz_name: str = DEFAULT_TZ) -> Iterator[Incoming]:
    """Yield one `Incoming` per photo, file or non-empty text message."""
    tz = ZoneInfo(tz_name)
    chat_id = data.get("id")
    for entry in data.get("messages", []):
        if entry.get("type") != "message":
            continue
        text = flatten_text(entry.get("text")).strip() or None
        common = dict(
            source="export",
            chat_id=chat_id,
            message_id=entry["id"],
            original_date=_date(entry, tz),
            author_user_id=_user_id(entry.get("from_id")),
            author_name=entry.get("from"),
            sender_user_id=None,
            forwarded="forwarded_from" in entry,
            text=text,
        )
        if "photo" in entry:
            path = entry["photo"]
            yield Incoming(kind="photo", mime_type="image/jpeg",
                           file_path=path if _exported(path) else None, **common)
        elif "file" in entry:
            path = entry["file"]
            mime = entry.get("mime_type") or mimetypes.guess_type(str(path))[0]
            if entry.get("media_type") or not is_receipt_mime(mime):
                continue  # stickers, voice, video, archives...
            yield Incoming(kind="document", mime_type=mime,
                           file_path=path if _exported(path) else None,
                           file_name=entry.get("file_name") or (Path(path).name if _exported(path) else None),
                           **common)
        elif text:
            yield Incoming(kind="text", **common)


def load_export(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
