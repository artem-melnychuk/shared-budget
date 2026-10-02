import unittest

from budget.balance import Debt, SplitRule, compute_balance, settle
from budget.storage import Expense

KEYS = ["alex", "sam"]


def expense(amount, payer, shared=True, currency="EUR", n=[0]):
    n[0] += 1
    return Expense(source="telegram", chat_id=1, message_id=n[0], kind="text",
                   original_date="2026-10-05T10:00:00+00:00", author=payer, payer=payer,
                   is_shared=shared, amount_cents=amount, currency=currency)


class SplitRuleTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(SplitRule.parse(None, KEYS).weights, {"alex": 1, "sam": 1})
        self.assertEqual(SplitRule.parse("60/40", KEYS).weights, {"alex": 60, "sam": 40})
        self.assertEqual(SplitRule.parse("2:1", KEYS).weights, {"alex": 2, "sam": 1})

    def test_parse_errors(self):
        for spec in ("60", "60/40/10", "a/b", "0/0", "-10/110"):
            with self.assertRaises(ValueError, msg=spec):
                SplitRule.parse(spec, KEYS)

    def test_shares_add_up_to_the_cent(self):
        even, sixty = SplitRule.even(KEYS), SplitRule.parse("60/40", KEYS)
        self.assertEqual(even.shares(1001), {"alex": 501, "sam": 500})
        self.assertEqual(even.shares(1), {"alex": 1, "sam": 0})
        self.assertEqual(sixty.shares(1001), {"alex": 601, "sam": 400})
        self.assertEqual(sixty.shares(999), {"alex": 599, "sam": 400})
        self.assertEqual(SplitRule.parse("100/0", KEYS).shares(777), {"alex": 777, "sam": 0})
        three = SplitRule({"a": 1, "b": 1, "c": 1})
        for amount in range(0, 50):
            self.assertEqual(sum(three.shares(amount).values()), amount)
            self.assertEqual(sum(sixty.shares(amount).values()), amount)


class ComputeBalanceTest(unittest.TestCase):
    def test_even_split(self):
        b = compute_balance([expense(10000, "alex"), expense(4000, "sam"), expense(3000, "sam", shared=False)],
                            SplitRule.even(KEYS))
        alex, sam = b.members["alex"], b.members["sam"]
        self.assertEqual((alex.paid, alex.share, alex.net, alex.spent), (10000, 7000, 3000, 7000))
        self.assertEqual((sam.paid, sam.paid_personal, sam.share, sam.net, sam.spent), (7000, 3000, 7000, -3000, 10000))
        self.assertEqual(b.debts, [Debt("sam", "alex", 3000)])
        self.assertEqual((b.shared_total, b.personal_total), (14000, 3000))

    def test_sixty_forty(self):
        b = compute_balance([expense(10000, "sam")], SplitRule.parse("60/40", KEYS))
        self.assertEqual(b.debts, [Debt("alex", "sam", 6000)])

    def test_personal_expenses_never_create_debt(self):
        b = compute_balance([expense(5000, "alex", shared=False)], SplitRule.even(KEYS))
        self.assertEqual(b.debts, [])
        self.assertEqual(b.members["alex"].paid, 5000)

    def test_skipped_expenses_are_counted_separately(self):
        b = compute_balance([expense(None, "alex"), expense(None, "sam"), expense(500, None),
                             expense(500, "m9"), expense(2000, "alex", currency="USD"), expense(800, "alex")],
                            SplitRule.even(KEYS))
        self.assertEqual((len(b.without_amount), len(b.without_payer), len(b.other_currency), len(b.counted)),
                         (2, 2, 1, 1))
        self.assertEqual(b.debts, [Debt("sam", "alex", 400)])

    def test_settle_three_members(self):
        debts = settle({"a": 3000, "b": -1000, "c": -2000})
        self.assertEqual(sorted(debts, key=lambda d: d.debtor), [Debt("b", "a", 1000), Debt("c", "a", 2000)])
        self.assertEqual(settle({"a": 0, "b": 0}), [])


if __name__ == "__main__":
    unittest.main()
