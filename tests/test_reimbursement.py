import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from unittest import mock

from budget.__main__ import main
from budget.balance import Debt, SplitRule, compute_balance
from budget.report import build_report, render
from budget.storage import Store
from budget.text_entry import parse_amount
from tests.fakes import ENV
from tests.test_report import add, fill

KEYS = ["alex", "sam"]
EVEN = SplitRule.even(KEYS)
OCT = date(2026, 10, 1)


def at(day, month=10):
    return datetime(2026, month, day, 12, tzinfo=timezone.utc)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()

    def test_add_reimbursement(self):
        first = self.store.add_reimbursement("sam", "alex", 2500, at(31), description="virement")
        second = self.store.add_reimbursement("sam", "alex", 2500, at(31))
        e = self.store.get(first)
        self.assertTrue(e.is_reimbursement)
        self.assertEqual((e.payer, e.paid_to, e.amount_cents, e.is_shared, e.source), ("sam", "alex", 2500, False, "manual"))
        self.assertEqual(e.description, "virement")
        # Two identical transfers are two transfers.
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.store.all()), 2)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            self.store.add_reimbursement("sam", "sam", 100, at(1))
        with self.assertRaises(ValueError):
            self.store.add_reimbursement("sam", "alex", 0, at(1))

    def test_mark_stored_entry_as_reimbursement(self):
        expense_id = add(self.store, "2026-10-05T10:00:00+00:00", 3000, "sam", "virement")
        self.store.mark_reimbursement(expense_id, "alex")
        e = self.store.get(expense_id)
        self.assertEqual((e.is_reimbursement, e.paid_to, e.is_shared), (True, "alex", False))
        self.store.mark_reimbursement(expense_id, None)
        self.assertFalse(self.store.get(expense_id).is_reimbursement)

    def test_old_database_gets_new_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE expenses (id INTEGER PRIMARY KEY, source TEXT NOT NULL, chat_id INTEGER,"
                       " message_id INTEGER NOT NULL, kind TEXT NOT NULL, original_date TEXT NOT NULL,"
                       " received_at TEXT NOT NULL, author TEXT, author_user_id INTEGER, author_name TEXT,"
                       " sender TEXT, forwarded INTEGER NOT NULL DEFAULT 0, payer TEXT,"
                       " payer_confirmed INTEGER NOT NULL DEFAULT 0, is_shared INTEGER NOT NULL DEFAULT 1,"
                       " amount_cents INTEGER, currency TEXT NOT NULL DEFAULT 'EUR', description TEXT,"
                       " category TEXT, text TEXT, media_group_id TEXT, file_id TEXT, file_unique_id TEXT,"
                       " file_path TEXT, file_name TEXT, mime_type TEXT, UNIQUE (source, chat_id, message_id))")
            db.execute("INSERT INTO expenses (source, chat_id, message_id, kind, original_date, received_at,"
                       " author, payer, amount_cents) VALUES ('telegram', 1, 1, 'text',"
                       " '2026-10-02T10:00:00+00:00', '2026-10-02T10:00:00+00:00', 'alex', 'alex', 500)")
            db.commit()
            db.close()
            store = Store(path)
            old = store.all()[0]
            self.assertEqual((old.is_reimbursement, old.paid_to), (False, None))
            store.add_reimbursement("sam", "alex", 250, at(3))
            self.assertEqual(compute_balance(store.all(), EVEN).debts, [])
            store.close()


class BalanceTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        add(self.store, "2026-10-03T09:00:00+00:00", 10000, "alex", "courses")

    def tearDown(self):
        self.store.close()

    def test_full_reimbursement_settles(self):
        self.store.add_reimbursement("sam", "alex", 5000, at(10))
        b = compute_balance(self.store.all(), EVEN)
        self.assertEqual(b.debts, [])
        self.assertEqual((b.members["sam"].sent, b.members["alex"].received), (5000, 5000))
        self.assertEqual(len(b.reimbursements), 1)

    def test_partial_and_over_reimbursement(self):
        self.store.add_reimbursement("sam", "alex", 2000, at(10))
        self.assertEqual(compute_balance(self.store.all(), EVEN).debts, [Debt("sam", "alex", 3000)])
        self.store.add_reimbursement("sam", "alex", 4000, at(11))
        self.assertEqual(compute_balance(self.store.all(), EVEN).debts, [Debt("alex", "sam", 1000)])

    def test_not_spending(self):
        self.store.add_reimbursement("sam", "alex", 5000, at(10))
        b = compute_balance(self.store.all(), EVEN)
        self.assertEqual((b.shared_total, b.personal_total), (10000, 0))
        self.assertEqual((b.members["sam"].paid, b.members["sam"].spent), (0, 5000))
        self.assertEqual(len(b.counted), 1)

    def test_independent_of_split_rule(self):
        self.store.add_reimbursement("sam", "alex", 4000, at(10))
        b = compute_balance(self.store.all(), SplitRule.parse("60/40", KEYS))
        self.assertEqual(b.debts, [])

    def test_receiver_not_a_member(self):
        e = self.store.get(self.store.add_reimbursement("sam", "m9", 1000, at(10)))
        b = compute_balance([e], EVEN)
        self.assertEqual((len(b.without_payer), b.debts), (1, []))

    def test_other_currency(self):
        self.store.add_reimbursement("sam", "alex", 1000, at(10), currency="USD")
        b = compute_balance(self.store.all(), EVEN)
        self.assertEqual(len(b.other_currency), 1)
        self.assertEqual(b.debts, [Debt("sam", "alex", 5000)])


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        fill(self.store)

    def tearDown(self):
        self.store.close()

    def test_month_and_running_balance(self):
        # Without it: October sam owes alex 25.00, up to the end of October 55.00.
        self.store.add_reimbursement("sam", "alex", 5500, at(31), description="virement")
        r = build_report(self.store, OCT, EVEN)
        self.assertEqual(r.month_balance.debts, [Debt("alex", "sam", 3000)])
        self.assertEqual(r.running_balance.debts, [])
        self.assertNotIn("other", r.categories)
        text = render(r)
        self.assertIn("2026-10-31 sam paid back alex 55.00 € (virement)", text)
        self.assertIn("paid back", text.split("By category")[0])
        self.assertIn("Counted: 5 expenses, 200.01 €", text)

    def test_reimbursement_in_a_later_month(self):
        self.store.add_reimbursement("sam", "alex", 5500, at(2, month=11))
        self.assertEqual(build_report(self.store, OCT, EVEN).running_balance.debts, [Debt("sam", "alex", 5500)])
        november = build_report(self.store, date(2026, 11, 1), EVEN)
        self.assertEqual(november.month_balance.members["sam"].sent, 5500)
        # November's own groceries (50.00 by alex, 25.00 each) remain.
        self.assertEqual(november.running_balance.debts, [Debt("sam", "alex", 2500)])

    def test_no_reimbursement_columns_without_reimbursements(self):
        text = render(build_report(self.store, OCT, EVEN))
        self.assertNotIn("paid back", text)
        self.assertNotIn("Reimbursements", text)


class ParseAmountTest(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(parse_amount("32"), 3200)
        self.assertEqual(parse_amount("32,5"), 3250)
        self.assertEqual(parse_amount(" 32.50 € "), 3250)
        for bad in ("", None, "0", "-5", "32.505", "abc", "32 courses"):
            self.assertIsNone(parse_amount(bad), bad)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "budget.db")
        store = Store(self.db)
        fill(store)
        store.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {**ENV, "BUDGET_DB": self.db}, clear=True), \
                redirect_stdout(out), mock.patch("sys.stderr", err):
            code = main(["--env", os.devnull, *args])
        return code, out.getvalue(), err.getvalue()

    def test_reimburse_then_report(self):
        code, out, _ = self.run_cli("reimburse", "--from", "sam", "--to", "alex", "--amount", "55",
                                    "--date", "2026-10-31", "--note", "virement")
        self.assertEqual(code, 0)
        self.assertIn("recorded: sam paid back alex 55.00 € on 2026-10-31", out)
        _, out, _ = self.run_cli("report", "--month", "2026-10")
        self.assertIn("2026-10-31 sam paid back alex 55.00 € (virement)", out)
        self.assertIn("Who owes whom, everything up to the end of 2026-10:\n  settled", out)

    def test_date_is_local_noon(self):
        self.run_cli("reimburse", "--from", "sam", "--to", "alex", "--amount", "1", "--date", "2026-10-31")
        store = Store(self.db)
        self.assertEqual([e.original_date for e in store.all() if e.is_reimbursement],
                         ["2026-10-31T11:00:00+00:00"])
        store.close()

    def test_bad_input(self):
        cases = [
            ("--from", "sam", "--to", "sam", "--amount", "5"),
            ("--from", "sam", "--to", "bob", "--amount", "5"),
            ("--from", "sam", "--to", "alex", "--amount", "five"),
            ("--from", "sam", "--to", "alex", "--amount", "5", "--date", "31/10/2026"),
        ]
        for args in cases:
            code, _, err = self.run_cli("reimburse", *args)
            self.assertEqual(code, 2, args)
            self.assertTrue(err, args)
        store = Store(self.db)
        self.assertFalse(any(e.is_reimbursement for e in store.all()))
        store.close()


if __name__ == "__main__":
    unittest.main()
