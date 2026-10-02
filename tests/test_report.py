import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from unittest import mock

from budget.__main__ import main
from budget.balance import Debt, SplitRule
from budget.report import build_report, month_bounds, money, parse_month, render
from budget.storage import Expense, Store
from tests.fakes import ENV

KEYS = ["alex", "sam"]


def add(store, when, amount, payer, description=None, shared=True, n=[0]):
    n[0] += 1
    return store.add(Expense(source="telegram", chat_id=1, message_id=n[0],
                             kind="photo" if amount is None else "text",
                             original_date=when, author=payer, payer=payer, is_shared=shared,
                             amount_cents=amount, description=description))


def fill(store):
    """Made-up month: October 2026, plus neighbours that must stay out of it."""
    add(store, "2026-09-15T12:00:00+00:00", 6000, "alex", "courses")        # September
    add(store, "2026-09-30T22:30:00+00:00", 2000, "sam", "parking")         # 1 Oct 00:30 in Nice
    add(store, "2026-10-03T09:00:00+00:00", 10000, "alex", "courses")
    add(store, "2026-10-08T19:30:00+00:00", 4000, "sam", "resto")
    add(store, "2026-10-12T08:00:00+00:00", 3000, "sam", "pharmacie", shared=False)
    add(store, "2026-10-14T08:00:00+00:00", 1001, "alex", "boulangerie")
    add(store, "2026-10-20T10:00:00+00:00", None, "alex")                   # receipt not read yet
    add(store, "2026-10-31T23:30:00+00:00", 5000, "alex", "courses")        # 1 Nov 00:30 in Nice


class MonthTest(unittest.TestCase):
    def test_parse_month(self):
        self.assertEqual(parse_month("2026-10"), date(2026, 10, 1))
        for bad in ("2026-13", "10-2026", "2026/10", ""):
            with self.assertRaises(ValueError):
                parse_month(bad)

    def test_bounds_follow_local_time(self):
        start, end = month_bounds(date(2026, 10, 1))
        self.assertEqual(start, datetime(2026, 9, 30, 22, tzinfo=timezone.utc))  # summer time
        self.assertEqual(end, datetime(2026, 10, 31, 23, tzinfo=timezone.utc))   # winter time
        start, end = month_bounds(date(2026, 12, 1))
        self.assertEqual(end, datetime(2026, 12, 31, 23, tzinfo=timezone.utc))

    def test_money(self):
        self.assertEqual(money(123456), "1234.56 €")
        self.assertEqual(money(-5), "-0.05 €")
        self.assertEqual(money(700, "USD"), "7.00 USD")


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        fill(self.store)

    def tearDown(self):
        self.store.close()

    def test_even_split(self):
        r = build_report(self.store, date(2026, 10, 1), SplitRule.even(KEYS))
        b = r.month_balance
        self.assertEqual(len(b.counted), 5)
        self.assertEqual(len(b.without_amount), 1)
        alex, sam = b.members["alex"], b.members["sam"]
        self.assertEqual((alex.paid_shared, alex.share, alex.net), (11001, 8501, 2500))
        self.assertEqual((sam.paid_shared, sam.paid_personal, sam.share, sam.net, sam.spent),
                         (6000, 3000, 8500, -2500, 11500))
        self.assertEqual(b.debts, [Debt("sam", "alex", 2500)])
        # Up to the end of October, the September groceries count too.
        self.assertEqual(r.running_balance.debts, [Debt("sam", "alex", 5500)])

    def test_sixty_forty(self):
        r = build_report(self.store, date(2026, 10, 1), SplitRule.parse("60/40", KEYS))
        self.assertEqual(r.month_balance.members["alex"].share, 10201)
        self.assertEqual(r.month_balance.debts, [Debt("sam", "alex", 800)])

    def test_categories(self):
        r = build_report(self.store, date(2026, 10, 1), SplitRule.even(KEYS))
        self.assertEqual(list(r.categories), ["groceries", "eating out", "health", "transport", "bakery"])
        groceries, health, bakery = r.categories["groceries"], r.categories["health"], r.categories["bakery"]
        self.assertEqual((groceries.total, groceries.shared, dict(groceries.spent_by)),
                         (10000, 10000, {"alex": 5000, "sam": 5000}))
        self.assertEqual((health.personal, dict(health.spent_by)), (3000, {"sam": 3000}))
        self.assertEqual(dict(bakery.spent_by), {"alex": 501, "sam": 500})
        spent = {k: sum(line.spent_by[k] for line in r.categories.values()) for k in KEYS}
        self.assertEqual(spent, {k: t.spent for k, t in r.month_balance.members.items()})

    def test_category_set_by_hand(self):
        e = [x for x in self.store.all() if x.description == "resto"][0]
        self.store.set_category(e.id, "date night")
        r = build_report(self.store, date(2026, 10, 1), SplitRule.even(KEYS))
        self.assertIn("date night", r.categories)
        self.assertNotIn("eating out", r.categories)

    def test_amount_filled_later_is_counted(self):
        e = [x for x in self.store.all() if x.amount_cents is None][0]
        self.store.set_amount(e.id, 2000)
        r = build_report(self.store, date(2026, 10, 1), SplitRule.even(KEYS))
        self.assertEqual((len(r.month_balance.counted), len(r.month_balance.without_amount)), (6, 0))
        self.assertIn("other", r.categories)

    def test_empty_month(self):
        r = build_report(self.store, date(2026, 6, 1), SplitRule.even(KEYS))
        text = render(r)
        self.assertIn("nothing this month", text)
        self.assertIn("settled", text)

    def test_render(self):
        text = render(build_report(self.store, date(2026, 10, 1), SplitRule.even(KEYS)))
        self.assertIn("Report 2026-10 (split 1/1 between alex, sam)", text)
        self.assertIn("1 without amount (receipt not recognised yet)", text)
        self.assertIn("sam owes alex 25.00 €", text)
        self.assertIn("sam owes alex 55.00 €", text)
        self.assertIn("groceries", text)


class OldDatabaseTest(unittest.TestCase):
    def test_category_column_is_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE expenses (id INTEGER PRIMARY KEY, source TEXT NOT NULL,"
                       " chat_id INTEGER, message_id INTEGER NOT NULL, kind TEXT NOT NULL,"
                       " original_date TEXT NOT NULL, received_at TEXT NOT NULL, author TEXT,"
                       " author_user_id INTEGER, author_name TEXT, sender TEXT,"
                       " forwarded INTEGER NOT NULL DEFAULT 0, payer TEXT,"
                       " payer_confirmed INTEGER NOT NULL DEFAULT 0, is_shared INTEGER NOT NULL DEFAULT 1,"
                       " amount_cents INTEGER, currency TEXT NOT NULL DEFAULT 'EUR', description TEXT,"
                       " text TEXT, media_group_id TEXT, file_id TEXT, file_unique_id TEXT,"
                       " file_path TEXT, file_name TEXT, mime_type TEXT,"
                       " UNIQUE (source, chat_id, message_id))")
            db.execute("INSERT INTO expenses (source, chat_id, message_id, kind, original_date, received_at,"
                       " author, payer, amount_cents, description) VALUES"
                       " ('telegram', 1, 1, 'text', '2026-10-02T10:00:00+00:00', '2026-10-02T10:00:00+00:00',"
                       " 'alex', 'alex', 500, 'café')")
            db.commit()
            db.close()
            store = Store(path)
            self.assertIsNone(store.all()[0].category)
            store.close()


class ReportCliTest(unittest.TestCase):
    def run_cli(self, *args, db=None, env_extra=None):
        out, err = io.StringIO(), io.StringIO()
        env = {**ENV, **(env_extra or {})}
        if db:
            env["BUDGET_DB"] = db
        with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out), \
                mock.patch("sys.stderr", err):
            code = main(["--env", os.devnull, "report", *args])
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "budget.db")
        store = Store(self.db)
        fill(store)
        store.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_month(self):
        code, out, _ = self.run_cli("--month", "2026-10", db=self.db)
        self.assertEqual(code, 0)
        self.assertIn("sam owes alex 25.00 €", out)

    def test_split_option_and_env(self):
        _, out, _ = self.run_cli("--month", "2026-10", "--split", "60/40", db=self.db)
        self.assertIn("split 60/40", out)
        self.assertIn("sam owes alex 8.00 €", out)
        _, out, _ = self.run_cli("--month", "2026-10", db=self.db, env_extra={"BUDGET_SPLIT": "60/40"})
        self.assertIn("sam owes alex 8.00 €", out)

    def test_bad_input(self):
        self.assertEqual(self.run_cli("--month", "oct", db=self.db)[0], 2)
        self.assertEqual(self.run_cli("--month", "2026-10", "--split", "60", db=self.db)[0], 2)
        code, _, err = self.run_cli("--month", "2026-10", db=os.path.join(self.tmp.name, "none.db"))
        self.assertEqual(code, 2)
        self.assertIn("No database", err)


if __name__ == "__main__":
    unittest.main()
