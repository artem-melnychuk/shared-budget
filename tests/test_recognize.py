"""Receipt recognition: checking the model's answer, filling in the expense, the queue.

Receipts here are made up; no real shop data or photos.
"""

import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from budget.gemini import GeminiError
from budget.recognize import Recognizer, apply_receipt, mime_of, parse_receipt
from budget.storage import Expense, Item, Store
from budget.telegram_api import TelegramError

TODAY = date(2026, 10, 4)

ANSWER = {
    "is_receipt": True,
    "merchant": "  Supermarché   Exemple ",
    "date": "2026-10-03",
    "total": 15.62,
    "currency": "eur",
    "card_last4": "**** 1234",
    "items": [
        {"name": "FRAISES 500G", "quantity": 1, "price": 6.9},
        {"name": "LAIT 1L", "quantity": 2, "price": 2.7},
        {"name": "YAOURT", "quantity": 1, "price": 6.55},
        {"name": "REMISE", "quantity": 1, "price": -0.53},
        {"name": "", "quantity": 1, "price": 1.0},          # no name: dropped
        {"name": "AIL", "quantity": 1, "price": "?"},       # no price: dropped
    ],
}


def photo_expense(**overrides) -> Expense:
    values = dict(source="telegram", chat_id=1001, message_id=10, kind="photo",
                  original_date="2026-10-04T10:15:00+00:00", author="alex", payer="alex",
                  file_id="big-r1", file_unique_id="r1", recognition="pending")
    values.update(overrides)
    return Expense(**values)


class ParseReceiptTest(unittest.TestCase):
    def test_a_good_answer(self):
        r = parse_receipt(ANSWER, TODAY)
        self.assertTrue(r.is_receipt)
        self.assertEqual((r.merchant, r.day, r.total_cents, r.currency, r.card_last4),
                         ("Supermarché Exemple", date(2026, 10, 3), 1562, "EUR", "1234"))
        self.assertEqual([i.name for i in r.items], ["FRAISES 500G", "LAIT 1L", "YAOURT", "REMISE"])
        self.assertEqual(r.items[3].amount_cents, -53)
        self.assertEqual(r.items[1].quantity, 2.0)
        self.assertEqual(r.items_total, 1562)
        self.assertTrue(r.items_match)

    def test_dates(self):
        def day(text):
            return parse_receipt({**ANSWER, "date": text}, TODAY).day
        self.assertEqual(day("03/10/2026"), date(2026, 10, 3))
        self.assertEqual(day("03/10/26"), date(2026, 10, 3))
        self.assertIsNone(day("2026-12-24"))      # in the future: a misreading
        self.assertIsNone(day("2023-10-03"))      # years back: a misreading
        self.assertIsNone(day(""))
        self.assertIsNone(day("le 3 octobre"))

    def test_unknown_values(self):
        r = parse_receipt({**ANSWER, "total": 0, "currency": "€", "card_last4": "12", "items": []}, TODAY)
        self.assertEqual((r.total_cents, r.currency, r.card_last4), (None, "EUR", None))
        self.assertFalse(r.items_match)

    def test_not_a_receipt(self):
        self.assertFalse(parse_receipt({"is_receipt": False}, TODAY).is_receipt)
        self.assertFalse(parse_receipt({}, TODAY).is_receipt)


class ApplyReceiptTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def add(self, **overrides):
        e = photo_expense(**overrides)
        self.store.add(e)
        return e

    def test_fills_what_is_missing(self):
        e = self.add()
        outcome = apply_receipt(self.store, e, parse_receipt(ANSWER, TODAY))
        e = outcome.expense
        self.assertEqual(outcome.status, "done")
        self.assertEqual((e.amount_cents, e.description, e.card_last4, e.recognition),
                         (1562, "Supermarché Exemple", "1234", "done"))
        # The receipt's day wins over the day the photo was sent; the time of day stays.
        self.assertEqual(e.original_date, "2026-10-03T10:15:00+00:00")
        self.assertEqual(len(self.store.items(e.id)), 4)
        self.assertFalse(outcome.total_differs)

    def test_what_people_typed_wins(self):
        e = self.add(amount_cents=1500, description="courses")
        outcome = apply_receipt(self.store, e, parse_receipt(ANSWER, TODAY))
        self.assertEqual((outcome.expense.amount_cents, outcome.expense.description), (1500, "courses"))
        self.assertTrue(outcome.total_differs)

    def test_unreadable_total_fails(self):
        e = self.add()
        outcome = apply_receipt(self.store, e, parse_receipt({**ANSWER, "total": 0}, TODAY))
        self.assertEqual((outcome.status, outcome.expense.recognition), ("failed", "failed"))
        self.assertIsNone(outcome.expense.amount_cents)

    def test_not_a_receipt_fails(self):
        e = self.add()
        outcome = apply_receipt(self.store, e, parse_receipt({"is_receipt": False}, TODAY))
        self.assertEqual(outcome.expense.recognition_error, "not a receipt")

    def test_reading_again_replaces_items(self):
        e = self.add()
        apply_receipt(self.store, e, parse_receipt(ANSWER, TODAY))
        apply_receipt(self.store, self.store.get(e.id), parse_receipt({**ANSWER, "items": ANSWER["items"][:1]}, TODAY))
        self.assertEqual(self.store.items(e.id), [Item("FRAISES 500G", 690, 1.0)])

    def test_items_go_with_their_expense(self):
        e = self.add()
        apply_receipt(self.store, e, parse_receipt(ANSWER, TODAY))
        self.store.delete(e.id)
        self.assertEqual(self.store.items(e.id), [])


class FakeTelegram:
    def __init__(self, error=None):
        self.downloaded = []
        self.error = error

    def download(self, file_id):
        self.downloaded.append(file_id)
        if self.error:
            raise self.error
        return b"\xff\xd8 fake jpeg"


class FakeReader:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def read_receipt(self, data, mime):
        self.calls.append(mime)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class RecognizerTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.clock = Clock()

    def tearDown(self):
        self.store.close()

    def recognizer(self, answers, telegram=None, **kwargs):
        self.reader = FakeReader(answers)
        self.telegram = telegram or FakeTelegram()
        return Recognizer(self.store, self.telegram, self.reader, clock=self.clock,
                          today=lambda: TODAY, **kwargs)

    def test_reads_the_queue_in_order(self):
        first = self.store.add(photo_expense())
        second = self.store.add(photo_expense(message_id=11, file_id="big-r2", file_unique_id="r2"))
        rec = self.recognizer([ANSWER, ANSWER])
        self.assertTrue(rec.due())
        self.assertEqual(rec.process_one().expense.id, first)
        self.assertEqual(rec.process_one().expense.id, second)
        self.assertEqual(self.telegram.downloaded, ["big-r1", "big-r2"])
        self.assertEqual(self.reader.calls, ["image/jpeg", "image/jpeg"])
        self.assertFalse(rec.due())
        self.assertIsNone(rec.process_one())

    def test_a_passing_failure_pauses_and_retries(self):
        e = self.store.add(photo_expense())
        rec = self.recognizer([GeminiError("Gemini 429: quota", retryable=True, retry_after=40), ANSWER])
        with self.assertLogs("budget.recognize", "WARNING") as logs:
            outcome = rec.process_one()
        self.assertIn("retrying in 40 s", logs.output[0])
        self.assertEqual(outcome.status, "retry")
        stored = self.store.get(e)
        self.assertEqual((stored.recognition, stored.recognition_attempts), ("pending", 1))
        self.assertFalse(rec.due())
        self.clock.now += 41
        self.assertTrue(rec.due())
        self.assertEqual(rec.process_one().status, "done")

    def test_gives_up_after_max_attempts(self):
        e = self.store.add(photo_expense())
        rec = self.recognizer([GeminiError("Gemini 503", retryable=True)] * 3, max_attempts=3)
        with self.assertLogs("budget.recognize", "WARNING"):
            for _ in range(2):
                self.assertEqual(rec.process_one().status, "retry")
                self.clock.now += 10_000
            outcome = rec.process_one()
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(self.store.get(e).recognition_attempts, 3)

    def test_a_lasting_failure_gives_up_at_once(self):
        e = self.store.add(photo_expense())
        rec = self.recognizer([GeminiError("Gemini 400: bad image", retryable=False)])
        with self.assertLogs("budget.recognize", "WARNING") as logs:
            self.assertEqual(rec.process_one().status, "failed")
        self.assertIn("giving up on receipt", logs.output[0])
        self.assertEqual(self.store.get(e).recognition_error, "Gemini 400: bad image")

    def test_telegram_errors(self):
        e = self.store.add(photo_expense())
        rec = self.recognizer([], telegram=FakeTelegram(TelegramError("download: network error: timeout")))
        with self.assertLogs("budget.recognize", "WARNING"):
            self.assertEqual(rec.process_one().status, "retry")
            self.clock.now += 10_000
            rec.telegram = FakeTelegram(TelegramError("getFile: Bad Request: file is too big", 400))
            self.assertEqual(rec.process_one().status, "failed")
        self.assertEqual(self.store.get(e).recognition, "failed")

    def test_transfers_are_not_read(self):
        e = self.store.add(photo_expense(is_reimbursement=True, paid_to="sam"))
        rec = self.recognizer([])
        self.assertIsNone(rec.process_one())
        self.assertIsNone(self.store.get(e).recognition)
        self.assertEqual(self.telegram.downloaded, [])

    def test_mime(self):
        self.assertEqual(mime_of(photo_expense()), "image/jpeg")
        self.assertEqual(mime_of(photo_expense(kind="document", mime_type="application/pdf")), "application/pdf")


class MigrationTest(unittest.TestCase):
    def test_receipts_stored_before_recognition_get_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "old.db")
            old = sqlite3.connect(path)
            old.executescript("""
                CREATE TABLE expenses (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, chat_id INTEGER, message_id INTEGER NOT NULL,
                    kind TEXT NOT NULL, original_date TEXT NOT NULL, received_at TEXT NOT NULL,
                    author TEXT, author_user_id INTEGER, author_name TEXT, sender TEXT,
                    forwarded INTEGER NOT NULL DEFAULT 0, payer TEXT, payer_confirmed INTEGER NOT NULL DEFAULT 0,
                    is_shared INTEGER NOT NULL DEFAULT 1, amount_cents INTEGER, currency TEXT NOT NULL DEFAULT 'EUR',
                    description TEXT, text TEXT, media_group_id TEXT, file_id TEXT, file_unique_id TEXT,
                    file_path TEXT, file_name TEXT, mime_type TEXT, UNIQUE (source, chat_id, message_id));
                INSERT INTO expenses (source, chat_id, message_id, kind, original_date, received_at, file_id)
                    VALUES ('telegram', 1, 1, 'photo', '2026-10-04T10:00:00+00:00', '2026-10-04T10:00:00+00:00', 'f1'),
                           ('telegram', 1, 2, 'text', '2026-10-04T10:00:00+00:00', '2026-10-04T10:00:00+00:00', NULL),
                           ('export', NULL, 3, 'photo', '2026-10-04T10:00:00+00:00', '2026-10-04T10:00:00+00:00', NULL);
            """)
            old.commit()
            old.close()
            store = Store(path)
            try:
                self.assertEqual([e.recognition for e in store.all()], ["pending", None, None])
                self.assertEqual(store.items(1), [])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
