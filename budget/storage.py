"""SQLite expense log.

Only facts are stored: who wrote it, who paid, shared or personal, the amount.
How a shared expense is split is a rule applied when balances are computed.

A reimbursement (money one member gives back to the other, as in Spliit) is a
row too: `is_reimbursement = 1`, `payer` sends, `paid_to` receives. It moves
the balance but is not spending, so it stays out of totals and categories.
"""

import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id              INTEGER PRIMARY KEY,
    source          TEXT    NOT NULL,           -- 'telegram' | 'export' | 'manual'
    chat_id         INTEGER,
    message_id      INTEGER NOT NULL,
    kind            TEXT    NOT NULL,           -- 'photo' | 'document' | 'text' | 'manual'
    original_date   TEXT    NOT NULL,           -- ISO 8601, UTC, when the author sent it
    received_at     TEXT    NOT NULL,           -- ISO 8601, UTC, when we stored it
    author          TEXT,                       -- member key of the original author
    author_user_id  INTEGER,
    author_name     TEXT,
    sender          TEXT,                       -- member key of whoever sent it to the bot
    forwarded       INTEGER NOT NULL DEFAULT 0,
    payer           TEXT,                       -- member key; defaults to author
    payer_confirmed INTEGER NOT NULL DEFAULT 0,
    is_shared       INTEGER NOT NULL DEFAULT 1,
    is_reimbursement INTEGER NOT NULL DEFAULT 0,
    paid_to         TEXT,                       -- member key receiving a reimbursement
    amount_cents    INTEGER,                    -- NULL until a receipt is recognised
    currency        TEXT    NOT NULL DEFAULT 'EUR',
    description     TEXT,
    category        TEXT,                       -- chosen by a person; NULL = guess from description
    text            TEXT,                       -- message text or caption as received
    media_group_id  TEXT,
    file_id         TEXT,
    file_unique_id  TEXT,
    file_path       TEXT,
    file_name       TEXT,
    mime_type       TEXT,
    UNIQUE (source, chat_id, message_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS expenses_file_unique_id
    ON expenses (file_unique_id) WHERE file_unique_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS expenses_author_date_amount
    ON expenses (author, original_date, amount_cents);
CREATE INDEX IF NOT EXISTS expenses_original_date
    ON expenses (original_date);
CREATE INDEX IF NOT EXISTS expenses_media_group
    ON expenses (media_group_id) WHERE media_group_id IS NOT NULL;

-- Bot messages showing an expense, so a reply to one can find it.
CREATE TABLE IF NOT EXISTS cards (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    expense_id  INTEGER NOT NULL REFERENCES expenses (id) ON DELETE CASCADE,
    PRIMARY KEY (chat_id, message_id)
);
"""


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Expense:
    source: str
    chat_id: int | None
    message_id: int
    kind: str
    original_date: str
    author: str | None
    payer: str | None
    sender: str | None = None
    author_user_id: int | None = None
    author_name: str | None = None
    forwarded: bool = False
    is_shared: bool = True
    is_reimbursement: bool = False
    paid_to: str | None = None
    payer_confirmed: bool = False
    amount_cents: int | None = None
    currency: str = "EUR"
    description: str | None = None
    category: str | None = None
    text: str | None = None
    media_group_id: str | None = None
    file_id: str | None = None
    file_unique_id: str | None = None
    file_path: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    received_at: str | None = None
    id: int | None = None


_COLUMNS = [f.name for f in fields(Expense) if f.name != "id"]


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        self.db.executescript(SCHEMA)

    def _migrate(self):
        """Add columns that databases created by older versions lack."""
        existing = {r["name"] for r in self.db.execute("PRAGMA table_info(expenses)")}
        added = {
            "category": "TEXT",
            "is_reimbursement": "INTEGER NOT NULL DEFAULT 0",
            "paid_to": "TEXT",
        }
        for column, definition in added.items():
            if existing and column not in existing:
                self.db.execute(f"ALTER TABLE expenses ADD COLUMN {column} {definition}")

    def close(self):
        self.db.close()

    def _expense(self, row) -> Expense | None:
        if row is None:
            return None
        data = dict(row)
        for flag in ("forwarded", "is_shared", "payer_confirmed", "is_reimbursement"):
            data[flag] = bool(data[flag])
        return Expense(**data)

    def get(self, expense_id: int) -> Expense | None:
        return self._expense(self.db.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())

    def all(self) -> list[Expense]:
        rows = self.db.execute("SELECT * FROM expenses ORDER BY original_date, id")
        return [self._expense(r) for r in rows]

    def between(self, start: datetime, end: datetime) -> list[Expense]:
        """Expenses whose original date is in [start, end)."""
        rows = self.db.execute(
            "SELECT * FROM expenses WHERE original_date >= ? AND original_date < ?"
            " ORDER BY original_date, id", (iso(start), iso(end)))
        return [self._expense(r) for r in rows]

    def media_group(self, media_group_id: str) -> list[Expense]:
        rows = self.db.execute(
            "SELECT * FROM expenses WHERE media_group_id = ? ORDER BY message_id",
            (media_group_id,))
        return [self._expense(r) for r in rows]

    def find_duplicate(self, e: Expense) -> Expense | None:
        """The stored expense this one repeats, if any.

        1. the same message seen again (re-delivered update, re-imported export);
        2. the same file: `file_unique_id` survives forwards;
        3. the same author, original date (to the second) and amount: matches a
           forwarded text against itself and an export entry against a forward.
        """
        row = self.db.execute(
            "SELECT * FROM expenses WHERE source = ? AND chat_id IS ? AND message_id = ?",
            (e.source, e.chat_id, e.message_id)).fetchone()
        if row is None and e.file_unique_id:
            row = self.db.execute(
                "SELECT * FROM expenses WHERE file_unique_id = ?", (e.file_unique_id,)).fetchone()
        if row is None and e.author and e.amount_cents is not None:
            row = self.db.execute(
                "SELECT * FROM expenses WHERE author = ? AND original_date = ? AND amount_cents = ?",
                (e.author, e.original_date, e.amount_cents)).fetchone()
        return self._expense(row)

    def add(self, e: Expense) -> int:
        e.received_at = e.received_at or iso(datetime.now(timezone.utc))
        values = [getattr(e, c) for c in _COLUMNS]
        cur = self.db.execute(
            f"INSERT INTO expenses ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
            values)
        self.db.commit()
        e.id = cur.lastrowid
        return e.id

    def add_reimbursement(self, payer: str, paid_to: str, amount_cents: int, when: datetime,
                          currency: str = "EUR", description: str | None = None) -> int:
        """Record money `payer` gave back to `paid_to` (bank transfer, cash...)."""
        if payer == paid_to:
            raise ValueError("a reimbursement goes from one member to another")
        if amount_cents <= 0:
            raise ValueError("a reimbursement must be a positive amount")
        last = self.db.execute(
            "SELECT MAX(message_id) FROM expenses WHERE source = 'manual'").fetchone()[0]
        return self.add(Expense(
            source="manual", chat_id=None, message_id=(last or 0) + 1, kind="manual",
            original_date=iso(when), author=payer, payer=payer, payer_confirmed=True,
            is_shared=False, is_reimbursement=True, paid_to=paid_to,
            amount_cents=amount_cents, currency=currency, description=description))

    def mark_reimbursement(self, expense_id: int, paid_to: str | None):
        """Turn a stored entry (say, a forwarded transfer screenshot) into a
        reimbursement to `paid_to`, or back into an expense with None."""
        self.db.execute(
            "UPDATE expenses SET is_reimbursement = ?, paid_to = ?,"
            " is_shared = CASE WHEN ? THEN 0 ELSE is_shared END WHERE id = ?",
            (int(paid_to is not None), paid_to, int(paid_to is not None), expense_id))
        self.db.commit()

    def delete(self, expense_id: int):
        self.db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        self.db.commit()

    def add_card(self, chat_id: int, message_id: int, expense_id: int):
        self.db.execute("INSERT OR REPLACE INTO cards (chat_id, message_id, expense_id) VALUES (?, ?, ?)",
                        (chat_id, message_id, expense_id))
        self.db.commit()

    def card_expense(self, chat_id: int, message_id: int) -> Expense | None:
        return self._expense(self.db.execute(
            "SELECT e.* FROM cards c JOIN expenses e ON e.id = c.expense_id"
            " WHERE c.chat_id = ? AND c.message_id = ?", (chat_id, message_id)).fetchone())

    def set_description(self, expense_id: int, description: str | None):
        self.db.execute("UPDATE expenses SET description = ? WHERE id = ?", (description, expense_id))
        self.db.commit()

    def set_paid_to(self, expense_id: int, paid_to: str | None):
        self.db.execute("UPDATE expenses SET paid_to = ? WHERE id = ?", (paid_to, expense_id))
        self.db.commit()

    def set_payer(self, expense_id: int, payer: str):
        self.db.execute("UPDATE expenses SET payer = ?, payer_confirmed = 1 WHERE id = ?",
                        (payer, expense_id))
        self.db.commit()

    def set_category(self, expense_id: int, category: str | None):
        self.db.execute("UPDATE expenses SET category = ? WHERE id = ?", (category, expense_id))
        self.db.commit()

    def set_amount(self, expense_id: int, amount_cents: int, currency: str = "EUR"):
        self.db.execute("UPDATE expenses SET amount_cents = ?, currency = ? WHERE id = ?",
                        (amount_cents, currency, expense_id))
        self.db.commit()

    def set_shared(self, expense_id: int, is_shared: bool):
        self.db.execute("UPDATE expenses SET is_shared = ? WHERE id = ?",
                        (int(is_shared), expense_id))
        self.db.commit()
