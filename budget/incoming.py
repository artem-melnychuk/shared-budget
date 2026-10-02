"""One incoming message, the same shape whatever channel it came through."""

from dataclasses import dataclass
from datetime import datetime

# Documents worth keeping: e-receipts arrive as PDFs or screenshots.
RECEIPT_MIME_PREFIXES = ("application/pdf", "image/")


def is_receipt_mime(mime: str | None) -> bool:
    return bool(mime) and mime.startswith(RECEIPT_MIME_PREFIXES)


@dataclass(frozen=True)
class Incoming:
    source: str                    # "telegram" or "export"
    chat_id: int | None
    message_id: int
    kind: str                      # "photo", "document" or "text"
    original_date: datetime        # when the author first sent it, UTC
    author_user_id: int | None     # None for a hidden forward author
    author_name: str | None
    sender_user_id: int | None     # who sent it to the bot (the forwarder); None for exports
    forwarded: bool = False
    text: str | None = None        # message text or media caption
    media_group_id: str | None = None
    file_id: str | None = None
    file_unique_id: str | None = None
    file_path: str | None = None   # relative path inside a chat export
    file_name: str | None = None
    mime_type: str | None = None
