"""From an incoming message to a stored expense: who, when, how much, once."""

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from budget.chat_export import DEFAULT_TZ, parse_export
from budget.incoming import Incoming
from budget.members import Members
from budget.storage import Expense, Store, iso
from budget.telegram_update import parse_update
from budget.text_entry import parse_text_expense


def on_day(when: datetime, day: date, tz_name: str = DEFAULT_TZ) -> datetime:
    """`when` moved to another calendar day, same local time of day.

    Keeping the time means two different messages that name the same day stay
    apart in the author+date+amount dedup, while the same message seen twice
    still matches itself.
    """
    local = when.astimezone(ZoneInfo(tz_name))
    return local.replace(year=day.year, month=day.month, day=day.day)


@dataclass
class Result:
    status: str                  # "added" | "duplicate" | "ignored"
    expense_id: int | None = None
    reason: str | None = None


def to_expense(msg: Incoming, members: Members,
               tz_name: str = DEFAULT_TZ) -> tuple[Expense | None, str | None]:
    """Build the expense to store, or (None, reason) when the message isn't one."""
    sender = members.by_user_id(msg.sender_user_id)
    if msg.source == "telegram" and sender is None:
        return None, "sender is not a member"
    author = members.resolve(msg.author_user_id, msg.author_name)
    if msg.source == "export" and author is None:
        return None, "author is not a member"

    sent_day = msg.original_date.astimezone(ZoneInfo(tz_name)).date()
    parsed = parse_text_expense(msg.text, sent_day)
    if msg.kind == "text" and parsed is None:
        return None, "text is not an amount"
    # A date written in the text ("12.50 boulangerie 01.10") wins over the message date.
    when = on_day(msg.original_date, parsed.day, tz_name) if parsed and parsed.day else msg.original_date

    # Default payer is the author; when the author is someone else (a shop's
    # channel, an unknown person) it's whoever forwarded it. The bot asks later.
    payer = author or sender
    payback = parsed is not None and parsed.is_reimbursement
    # A payback goes to the other member; with more than two it waits for a choice.
    others = [m for m in members.members if payer and m.key != payer.key]
    return Expense(
        source=msg.source,
        chat_id=msg.chat_id,
        message_id=msg.message_id,
        kind=msg.kind,
        original_date=iso(when),
        author=author.key if author else None,
        author_user_id=msg.author_user_id,
        author_name=msg.author_name,
        sender=sender.key if sender else None,
        forwarded=msg.forwarded,
        payer=payer.key if payer else None,
        is_shared=not payback,
        is_reimbursement=payback,
        paid_to=others[0].key if payback and len(others) == 1 else None,
        amount_cents=parsed.amount_cents if parsed else None,
        description=parsed.description if parsed else None,
        text=msg.text,
        media_group_id=msg.media_group_id,
        file_id=msg.file_id,
        file_unique_id=msg.file_unique_id,
        file_path=msg.file_path,
        file_name=msg.file_name,
        mime_type=msg.mime_type,
    ), None


def ingest(store: Store, members: Members, msg: Incoming, tz_name: str = DEFAULT_TZ) -> Result:
    expense, reason = to_expense(msg, members, tz_name)
    if expense is None:
        return Result("ignored", reason=reason)
    if (dup := store.find_duplicate(expense)) is not None:
        return Result("duplicate", expense_id=dup.id)
    return Result("added", expense_id=store.add(expense))


def ingest_update(store: Store, members: Members, update: dict, tz_name: str = DEFAULT_TZ) -> Result:
    msg = parse_update(update)
    if msg is None:
        return Result("ignored", reason="no photo, receipt document or text")
    return ingest(store, members, msg, tz_name)


@dataclass
class ImportSummary:
    added: int = 0
    duplicate: int = 0
    ignored: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


def import_export(store: Store, members: Members, data: dict, tz_name: str | None = None) -> ImportSummary:
    summary = ImportSummary()
    kwargs = {"tz_name": tz_name} if tz_name else {}
    for msg in parse_export(data, **kwargs):
        result = ingest(store, members, msg, **kwargs)
        setattr(summary, result.status, getattr(summary, result.status) + 1)
        if result.reason:
            summary.reasons[result.reason] = summary.reasons.get(result.reason, 0) + 1
    return summary
