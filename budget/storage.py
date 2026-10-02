"""SQLite expense log.

Only facts are stored: who wrote it, who paid, shared or personal, the amount.
How a shared expense is split is a rule applied when balances are computed.
"""

import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id              INTEGER PRIMARY KEY,
    source          TEXT    NOT NULL,           -- 'telegram' | 'export'
    chat_id         INTEGER,
    message_id      INTEGER NOT NULL,
    kind            TEXT    NOT NULL,           -- 'photo' | 'document' | 'text'
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
        self._migrate()
        self.db.executescript(SCHEMA)

    def _migrate(self):
        """Add columns that databases created by older versions lack."""
        existing = {r["name"] for r in self.db.execute("PRAGMA table_info(expenses)")}
        if existing and "category" not in existing:
            self.db.execute("ALTER TABLE expenses ADD COLUMN category TEXT")

    def close(self):
        self.db.close()

    def _expense(self, row) -> Expense | None:
        if row is None:
            return None
        data = dict(row)
        for flag in ("forwarded", "is_shared", "payer_confirmed"):
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
