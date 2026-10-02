"""From an incoming message to a stored expense: who, when, how much, once."""

from dataclasses import dataclass, field

from budget.chat_export import parse_export
from budget.incoming import Incoming
from budget.members import Members
from budget.storage import Expense, Store, iso
from budget.telegram_update import parse_update
from budget.text_entry import parse_text_expense


@dataclass
class Result:
    status: str                  # "added" | "duplicate" | "ignored"
    expense_id: int | None = None
    reason: str | None = None


def to_expense(msg: Incoming, members: Members) -> tuple[Expense | None, str | None]:
    """Build the expense to store, or (None, reason) when the message isn't one."""
    sender = members.by_user_id(msg.sender_user_id)
    if msg.source == "telegram" and sender is None:
        return None, "sender is not a member"
    author = members.resolve(msg.author_user_id, msg.author_name)
    if msg.source == "export" and author is None:
        return None, "author is not a member"

    parsed = parse_text_expense(msg.text)
    if msg.kind == "text" and parsed is None:
        return None, "text is not an amount"

    # Default payer is the author; when the author is someone else (a shop's
    # channel, an unknown person) it's whoever forwarded it. The bot asks later.
    payer = author or sender
    return Expense(
        source=msg.source,
        chat_id=msg.chat_id,
        message_id=msg.message_id,
        kind=msg.kind,
        original_date=iso(msg.original_date),
        author=author.key if author else None,
        author_user_id=msg.author_user_id,
        author_name=msg.author_name,
        sender=sender.key if sender else None,
        forwarded=msg.forwarded,
        payer=payer.key if payer else None,
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


def ingest(store: Store, members: Members, msg: Incoming) -> Result:
    expense, reason = to_expense(msg, members)
    if expense is None:
        return Result("ignored", reason=reason)
    if (dup := store.find_duplicate(expense)) is not None:
        return Result("duplicate", expense_id=dup.id)
    return Result("added", expense_id=store.add(expense))


def ingest_update(store: Store, members: Members, update: dict) -> Result:
    msg = parse_update(update)
    if msg is None:
        return Result("ignored", reason="no photo, receipt document or text")
    return ingest(store, members, msg)


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
        result = ingest(store, members, msg)
        setattr(summary, result.status, getattr(summary, result.status) + 1)
        if result.reason:
            summary.reasons[result.reason] = summary.reasons.get(result.reason, 0) + 1
    return summary
