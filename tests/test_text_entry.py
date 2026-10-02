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


class PaybackTextTest(unittest.TestCase):
    def check(self, text, cents, description=""):
        parsed = parse_text_expense(text)
        self.assertIsNotNone(parsed, text)
        self.assertEqual((parsed.amount_cents, parsed.description, parsed.is_reimbursement),
                         (cents, description, True), text)

    def test_word_first(self):
        self.check("remboursé 32", 3200)
        self.check("Rembourse 32,50 virement", 3250, "virement")
        self.check("remboursement : 15€", 1500)
        self.check("remb. 10", 1000)
        self.check("вернул 32", 3200)
        self.check("Вернула долг 15,20 €", 1520)
        self.check("возврат долга: 20", 2000)
        self.check("отдал 5 наличными", 500, "наличными")

    def test_word_after_amount(self):
        self.check("32 remboursé", 3200)
        self.check("32 euros remboursés", 3200)
        self.check("32 remboursement loyer", 3200, "loyer")
        self.check("32 вернул", 3200)

    def test_not_a_payback(self):
        for text in ("remboursé", "вернул книгу", "12.50 boulangerie", "35 courses rembourser plus tard"):
            parsed = parse_text_expense(text)
            self.assertFalse(parsed and parsed.is_reimbursement, text)


if __name__ == "__main__":
    unittest.main()
