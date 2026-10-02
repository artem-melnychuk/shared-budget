import unittest

from budget.text_entry import parse_text_expense


class ParseTextExpenseTest(unittest.TestCase):
    def check(self, text, cents, description):
        parsed = parse_text_expense(text)
        self.assertIsNotNone(parsed, text)
        self.assertEqual((parsed.amount_cents, parsed.description), (cents, description))

    def test_amount_first(self):
        self.check("12.50 boulangerie", 1250, "boulangerie")
        self.check("35 courses", 3500, "courses")
        self.check("12,5 pain", 1250, "pain")
        self.check("  4,20€ café en terrasse ", 420, "café en terrasse")
        self.check("€7.10 parking", 710, "parking")
        self.check("18 EUR cinéma", 1800, "cinéma")
        self.check("42", 4200, "")

    def test_amount_last_needs_currency(self):
        self.check("boulangerie 3,40€", 340, "boulangerie")
        self.check("marché 22 euros", 2200, "marché")
        self.assertIsNone(parse_text_expense("see you at 7"))

    def test_not_an_expense(self):
        for text in ("", None, "ok", "merci !", "0 rien", "0612345678 appelle-moi",
                     "12.505 trois décimales", "26/03 rdv"):
            self.assertIsNone(parse_text_expense(text), text)


if __name__ == "__main__":
    unittest.main()
