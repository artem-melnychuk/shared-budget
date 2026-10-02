import unittest
from datetime import date, datetime, timezone

from budget import texts
from budget.balance import SplitRule
from budget.report import build_report, render
from budget.savings import Recurring, SmallSpending, analyze
from budget.storage import Store
from tests.fakes import members
from tests.test_report import add

KEYS = ["alex", "sam"]
EVEN = SplitRule.even(KEYS)
OCT = date(2026, 10, 1)


def fill(store):
    """Made-up August to October."""
    for month, day in ((8, 5), (9, 5), (10, 5)):
        add(store, f"2026-{month:02d}-{day:02d}T08:00:00+00:00", 1349, "alex", "Netflix" if month != 9 else "netflix")
    add(store, "2026-08-10T08:00:00+00:00", 1999, "sam", "Free mobile")       # skips September
    add(store, "2026-10-10T08:00:00+00:00", 1999, "sam", "Free mobile")
    add(store, "2026-08-12T08:00:00+00:00", 1099, "alex", "Spotify")          # price went up in October
    add(store, "2026-09-12T08:00:00+00:00", 1099, "alex", "Spotify")
    add(store, "2026-10-12T08:00:00+00:00", 1199, "alex", "Spotify")
    add(store, "2026-09-15T08:00:00+00:00", 2999, "sam", "Basic-Fit")         # only two months
    add(store, "2026-10-15T08:00:00+00:00", 2999, "sam", "Basic-Fit")
    add(store, "2026-09-20T18:00:00+00:00", 2000, "alex", "resto")
    add(store, "2026-09-21T10:00:00+00:00", 8000, "alex", "courses")
    for day in range(1, 10):                                                  # 9 small bakery buys
        add(store, f"2026-10-{day:02d}T07:00:00+00:00", 150, "sam", "boulangerie")
    add(store, "2026-10-11T07:00:00+00:00", 1100, "sam", "boulangerie")       # not small
    for day in range(1, 8):                                                   # 7 coffees: below the count
        add(store, f"2026-10-{day:02d}T09:00:00+00:00", 250, "alex", "café")
    add(store, "2026-10-17T19:00:00+00:00", 2500, "alex", "Deliveroo")
    add(store, "2026-10-18T19:00:00+00:00", 4000, "sam", "resto")
    add(store, "2026-10-19T10:00:00+00:00", 10000, "alex", "courses", shared=False)
    add(store, "2026-10-20T10:00:00+00:00", None, "alex")                     # no amount: ignored
    store.add_reimbursement("sam", "alex", 1349, datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
                            description="Netflix")                            # not spending


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        fill(self.store)

    def tearDown(self):
        self.store.close()

    def test_recurring(self):
        s = analyze(self.store, OCT, EVEN, "Europe/Paris")
        self.assertEqual(s.recurring, [Recurring("Netflix", 1349, 3)])
        self.assertEqual(s.recurring[0].yearly_cents, 16188)

    def test_small_spending(self):
        s = analyze(self.store, OCT, EVEN, "Europe/Paris")
        self.assertEqual(s.small, [SmallSpending("bakery", 9, 1350)])

    def test_delivery_and_eating_out(self):
        e = analyze(self.store, OCT, EVEN, "Europe/Paris").eating
        self.assertEqual(e.by_category, {"delivery": 2500, "eating out": 5750})
        self.assertEqual(e.total_cents, 28246)
        self.assertAlmostEqual(e.share, 8250 / 28246)
        self.assertAlmostEqual(e.previous_share, 2000 / 15447)

    def test_not_enough_history(self):
        s = analyze(self.store, date(2026, 9, 1), EVEN, "Europe/Paris")
        self.assertEqual(s.recurring, [])

    def test_empty_month(self):
        s = analyze(self.store, date(2027, 3, 1), EVEN, "Europe/Paris")
        self.assertTrue(s.empty)
        self.assertIsNone(s.eating.share)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        fill(self.store)

    def tearDown(self):
        self.store.close()

    def test_cli_report(self):
        text = render(build_report(self.store, OCT, EVEN))
        self.assertIn("Where to save", text)
        self.assertIn("Netflix: 13.49 € a month, 161.88 € a year", text)
        self.assertIn("bakery: 9 times, 13.50 €", text)
        self.assertIn("Delivery and eating out: 82.50 € (delivery 25.00 €, eating out 57.50 €), "
                      "29% of spending; previous month 13%", text)

    def test_bot_report(self):
        text = texts.report_message(build_report(self.store, OCT, EVEN), members())
        self.assertIn("<b>Где можно сэкономить</b>", text)
        self.assertIn("• Netflix: 13,49 € в месяц, 161,88 € в год", text)
        self.assertIn("• Булочная: 9 раз, всего 13,50 €", text)
        self.assertIn("🍽 Доставка и рестораны: 82,50 € (доставка 25,00 €, кафе и рестораны 57,50 €) — 29% всех трат; "
                      "в прошлом месяце 13%", text)

    def test_nothing_to_say(self):
        report = build_report(self.store, date(2027, 3, 1), EVEN)
        self.assertIn("nothing stands out", render(report))
        self.assertIn("Ничего не бросается в глаза.", texts.report_message(report, members()))

    def test_seller_is_escaped_for_telegram(self):
        for month in (8, 9, 10):
            add(self.store, f"2026-{month:02d}-03T08:00:00+00:00", 500, "alex", "<b>shop</b>")
        text = texts.report_message(build_report(self.store, OCT, EVEN), members())
        self.assertIn("&lt;b&gt;shop&lt;/b&gt;", text)


if __name__ == "__main__":
    unittest.main()
