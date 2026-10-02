import csv
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest import mock

from budget.__main__ import main
from budget.balance import SplitRule
from budget.export import write_csv
from budget.storage import Store
from tests.fakes import ENV, members
from tests.test_report import add, fill

KEYS = ["alex", "sam"]


def read(text, delimiter):
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=delimiter))


class WriteCsvTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        fill(self.store)
        self.store.add_reimbursement("sam", "alex", 3000, datetime(2026, 10, 31, 12, tzinfo=timezone.utc),
                                     description="virement")

    def tearDown(self):
        self.store.close()

    def export(self, plain=False, rule=None):
        out = io.StringIO()
        count = write_csv(out, self.store.all(), members(), rule or SplitRule.even(KEYS), "Europe/Paris", plain)
        return count, out.getvalue()

    def test_excel_flavour(self):
        count, text = self.export()
        self.assertEqual(count, 9)
        self.assertTrue(text.startswith("﻿id;date;time;month;type;amount;amount_cents"))
        self.assertIn("\r\n", text)
        rows = {r["id"]: r for r in read(text, ";")}
        boulangerie = next(r for r in rows.values() if r["description"] == "boulangerie")
        self.assertEqual((boulangerie["amount"], boulangerie["amount_cents"], boulangerie["category"]),
                         ("10,01", "1001", "bakery"))
        self.assertEqual((boulangerie["share_alex"], boulangerie["share_sam"]), ("5,01", "5,00"))
        self.assertEqual((boulangerie["payer"], boulangerie["payer_name"], boulangerie["shared"]),
                         ("alex", "Alex Example", "yes"))

    def test_plain_flavour(self):
        _, text = self.export(plain=True)
        self.assertTrue(text.startswith("id,date,time"))
        rows = read(text, ",")
        self.assertIn("10.01", [r["amount"] for r in rows])

    def test_local_dates(self):
        rows = read(self.export()[1], ";")
        parking = next(r for r in rows if r["description"] == "parking")
        # 22:30 UTC on 30 Sep is 1 Oct in Nice.
        self.assertEqual((parking["date"], parking["time"], parking["month"]), ("2026-10-01", "00:30", "2026-10"))

    def test_personal_without_amount_and_reimbursement(self):
        rows = read(self.export(rule=SplitRule.parse("60/40", KEYS))[1], ";")
        pharmacie = next(r for r in rows if r["description"] == "pharmacie")
        self.assertEqual((pharmacie["shared"], pharmacie["share_sam"], pharmacie["share_alex"]), ("no", "30,00", "0,00"))
        courses = next(r for r in rows if r["amount_cents"] == "10000")
        self.assertEqual((courses["share_alex"], courses["share_sam"]), ("60,00", "40,00"))
        blank = next(r for r in rows if r["kind"] == "photo")
        self.assertEqual((blank["amount"], blank["amount_cents"], blank["share_alex"]), ("", "", ""))
        payback = next(r for r in rows if r["type"] == "reimbursement")
        self.assertEqual((payback["payer"], payback["paid_to"], payback["amount"], payback["category"],
                          payback["shared"], payback["share_alex"]), ("sam", "alex", "30,00", "", "", ""))

    def test_formula_injection_is_defused(self):
        add(self.store, "2026-10-05T10:00:00+00:00", 100, "alex", "=HYPERLINK(\"x\")")
        rows = read(self.export()[1], ";")
        self.assertIn("'=HYPERLINK(\"x\")", [r["description"] for r in rows])

    def test_quotes_and_separators(self):
        add(self.store, "2026-10-05T10:00:00+00:00", 100, "alex", 'pain; "bio", 2x')
        rows = read(self.export()[1], ";")
        self.assertIn('pain; "bio", 2x', [r["description"] for r in rows])


class ExportCliTest(unittest.TestCase):
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
            code = main(["--env", os.devnull, "export", *args])
        return code, out.getvalue(), err.getvalue()

    def test_month_to_default_file(self):
        code, out, _ = self.run_cli("--month", "2026-10")
        self.assertEqual(code, 0)
        path = os.path.join(self.tmp.name, "expenses-2026-10.csv")
        self.assertIn(f"6 rows written to {path}", out)
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["month"] == "2026-10" for r in rows))

    def test_everything_to_stdout_plain(self):
        code, out, _ = self.run_cli("--out", "-", "--plain")
        self.assertEqual(code, 0)
        self.assertEqual(len(read(out, ",")), 8)

    def test_bad_input(self):
        self.assertEqual(self.run_cli("--month", "oct")[0], 2)
        self.assertEqual(self.run_cli("--split", "1")[0], 2)
        os.remove(self.db)
        self.assertEqual(self.run_cli()[0], 2)


if __name__ == "__main__":
    unittest.main()
