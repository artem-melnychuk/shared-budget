"""Receipt recognition: a queue of photos and PDFs, read one at a time.

Every receipt sent through Telegram is stored at once with `recognition =
'pending'`; `Recognizer.process_one` downloads it again from Telegram, asks the
model, checks the answer and fills in what the people haven't: an amount typed
by hand, a description or a category chosen on the card always win. Items are
saved to their own table. A failure that may pass (quota, network) leaves the
receipt pending and pauses the queue; after `max_attempts`, or on a failure
that won't pass, it becomes 'failed' and the card asks for the amount, as before.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from budget.chat_export import DEFAULT_TZ
from budget.gemini import GeminiError
from budget.ingest import on_day
from budget.storage import Expense, Item, Store, iso
from budget.telegram_api import TelegramError

log = logging.getLogger(__name__)

MAX_AGE_DAYS = 400       # a receipt date older than this is a misreading, not a purchase
MATCH_TOLERANCE = 2      # cents: items summing to the total within this "match"


@dataclass
class Receipt:
    is_receipt: bool
    merchant: str = ""
    day: date | None = None
    total_cents: int | None = None
    currency: str = "EUR"
    card_last4: str | None = None
    items: list[Item] = field(default_factory=list)

    @property
    def items_total(self) -> int:
        return sum(i.amount_cents for i in self.items)

    @property
    def items_match(self) -> bool:
        return self.total_cents is not None and abs(self.items_total - self.total_cents) <= MATCH_TOLERANCE


def _cents(value) -> int | None:
    try:
        return round(float(value) * 100)
    except (TypeError, ValueError):
        return None


def _day(text, today: date) -> date | None:
    text = str(text or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d.%m.%Y"):
        try:
            day = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        # A date in the future or years back is a misreading: keep the message date.
        return day if today - timedelta(days=MAX_AGE_DAYS) <= day <= today + timedelta(days=1) else None
    return None


def parse_receipt(data: dict, today: date) -> Receipt:
    """Turn the model's JSON into checked values; anything implausible becomes "unknown"."""
    if not data.get("is_receipt"):
        return Receipt(is_receipt=False)
    total = _cents(data.get("total"))
    currency = str(data.get("currency") or "").strip().upper()
    last4 = "".join(ch for ch in str(data.get("card_last4") or "") if ch.isdigit())
    items = []
    for raw in data.get("items") or []:
        name = " ".join(str(raw.get("name") or "").split())
        cents = _cents(raw.get("price"))
        if not name or cents is None:
            continue
        quantity = raw.get("quantity")
        quantity = float(quantity) if isinstance(quantity, (int, float)) and quantity > 0 else None
        items.append(Item(name, cents, quantity))
    return Receipt(
        is_receipt=True,
        merchant=" ".join(str(data.get("merchant") or "").split()),
        day=_day(data.get("date"), today),
        total_cents=total if total and total > 0 else None,
        currency=currency if len(currency) == 3 and currency.isalpha() else "EUR",
        card_last4=last4 if len(last4) == 4 else None,
        items=items,
    )


@dataclass
class Outcome:
    """What happened to one receipt, for the bot to report."""
    expense: Expense
    status: str                    # "done" | "failed" | "retry"
    receipt: Receipt | None = None
    total_differs: bool = False    # the receipt's total differs from an amount typed by hand
    error: str | None = None


def apply_receipt(store: Store, e: Expense, r: Receipt, tz_name: str = DEFAULT_TZ) -> Outcome:
    if not r.is_receipt:
        store.set_recognition(e.id, "failed", "not a receipt")
        return Outcome(store.get(e.id), "failed", r, error="not a receipt")
    if r.total_cents is None:
        store.set_recognition(e.id, "failed", "total not readable")
        return Outcome(store.get(e.id), "failed", r, error="total not readable")
    differs = e.amount_cents is not None and e.amount_cents != r.total_cents
    if e.amount_cents is None:
        store.set_amount(e.id, r.total_cents, r.currency)
    if r.day is not None:
        sent = datetime.fromisoformat(e.original_date)
        if sent.astimezone(ZoneInfo(tz_name)).date() != r.day:
            store.set_date(e.id, iso(on_day(sent, r.day, tz_name)))
    if r.merchant and not e.description:
        store.set_description(e.id, r.merchant)
    if r.card_last4:
        store.set_card_last4(e.id, r.card_last4)
    store.replace_items(e.id, r.items)
    store.set_recognition(e.id, "done")
    return Outcome(store.get(e.id), "done", r, total_differs=differs)


def mime_of(e: Expense) -> str:
    return "image/jpeg" if e.kind == "photo" else (e.mime_type or "application/octet-stream")


class Recognizer:
    """Reads the queue one receipt at a time; pauses after a failure that may pass."""

    def __init__(self, store: Store, telegram, reader, tz_name: str = DEFAULT_TZ,
                 max_attempts: int = 5, clock=time.monotonic, today=None):
        self.store = store
        self.telegram = telegram           # has download(file_id) -> bytes
        self.reader = reader               # has read_receipt(bytes, mime) -> dict
        self.tz_name = tz_name
        self.max_attempts = max_attempts
        self.clock = clock
        self.today = today or (lambda: datetime.now(ZoneInfo(tz_name)).date())
        self.paused_until = 0.0
        self.backoff = 30.0

    def due(self) -> bool:
        return self.clock() >= self.paused_until and self.store.has_pending_recognition()

    def process_one(self) -> Outcome | None:
        e = self.store.next_pending()
        if e is None:
            return None
        if e.is_reimbursement or not e.file_id:
            self.store.set_recognition(e.id, None)       # a transfer, or nothing to download
            return None
        try:
            data = self.telegram.download(e.file_id)
            receipt = parse_receipt(self.reader.read_receipt(data, mime_of(e)), self.today())
        except (GeminiError, TelegramError) as err:
            return self._failed(e, err)
        self.backoff = 30.0
        return apply_receipt(self.store, e, receipt, self.tz_name)

    def _failed(self, e: Expense, err: Exception) -> Outcome:
        attempts = e.recognition_attempts + 1
        retryable = getattr(err, "retryable", None)
        if retryable is None:  # a Telegram error: a network hiccup or rate limit may pass
            retryable = err.code is None or err.code == 429 or err.code >= 500
        if retryable and attempts < self.max_attempts:
            delay = getattr(err, "retry_after", None) or self.backoff
            self.paused_until = self.clock() + delay
            self.backoff = min(self.backoff * 2, 3600)
            log.warning("reading receipt #%s failed (%s); retrying in %.0f s", e.id, err, delay)
            self.store.set_recognition(e.id, "pending", str(err), attempts)
            return Outcome(self.store.get(e.id), "retry", error=str(err))
        log.warning("giving up on receipt #%s: %s", e.id, err)
        self.store.set_recognition(e.id, "failed", str(err), attempts)
        return Outcome(self.store.get(e.id), "failed", error=str(err))
