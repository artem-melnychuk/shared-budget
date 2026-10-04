import unittest
from datetime import date

from budget.text_entry import parse_date_only, parse_text_expense

SENT = date(2026, 10, 4)


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


class TextDateTest(unittest.TestCase):
    def check(self, text, cents, description, day, sent=SENT, payback=False):
        parsed = parse_text_expense(text, sent)
        self.assertIsNotNone(parsed, text)
        self.assertEqual((parsed.amount_cents, parsed.description, parsed.day, parsed.is_reimbursement),
                         (cents, description, day, payback), text)

    def test_day_and_month(self):
        self.check("12.50 boulangerie 01.10", 1250, "boulangerie", date(2026, 10, 1))
        self.check("12.50 boulangerie 1/10", 1250, "boulangerie", date(2026, 10, 1))
        self.check("12 01.10", 1200, "", date(2026, 10, 1))
        self.check("boulangerie 3,40€ 01.10", 340, "boulangerie", date(2026, 10, 1))

    def test_with_a_year(self):
        self.check("5 café 01.10.2025", 500, "café", date(2025, 10, 1))
        self.check("5 café 01/10/25", 500, "café", date(2025, 10, 1))

    def test_without_a_year_never_in_the_future(self):
        self.check("40 resto 05.11", 4000, "resto", date(2025, 11, 5))
        self.check("40 resto 28.12", 4000, "resto", date(2026, 12, 28), sent=date(2027, 1, 3))
        self.check("40 resto 04.10", 4000, "resto", date(2026, 10, 4))

    def test_words(self):
        self.check("5 café вчера", 500, "café", date(2026, 10, 3))
        self.check("5 café позавчера", 500, "café", date(2026, 10, 2))
        self.check("5 café hier", 500, "café", date(2026, 10, 3))
        self.check("5 café avant-hier", 500, "café", date(2026, 10, 2))

    def test_payback_with_a_date(self):
        self.check("вернул 32 01.10", 3200, "", date(2026, 10, 1), payback=True)

    def test_not_a_date(self):
        self.check("12.50 boulangerie 31.02", 1250, "boulangerie 31.02", None)
        self.check("12.10", 1210, "", None)          # alone it's an amount
        self.check("12.50 bus 3", 1250, "bus 3", None)

    def test_dates_are_read_only_when_the_send_day_is_known(self):
        parsed = parse_text_expense("12.50 boulangerie 01.10")
        self.assertEqual((parsed.description, parsed.day), ("boulangerie 01.10", None))


class DateOnlyTest(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_date_only("01/10", SENT), date(2026, 10, 1))
        self.assertEqual(parse_date_only(" 01.10.2026 ", SENT), date(2026, 10, 1))
        self.assertEqual(parse_date_only("Вчера", SENT), date(2026, 10, 3))

    def test_not_a_date(self):
        for text in ("01.10", "23,90", "23,90 01.10", "", None, "31/02"):
            self.assertIsNone(parse_date_only(text, SENT), text)


if __name__ == "__main__":
    unittest.main()
