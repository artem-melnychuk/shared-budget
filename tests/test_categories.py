import unittest

from budget.categories import UNCATEGORIZED, category_of, guess_category
from budget.storage import Expense


class CategoriesTest(unittest.TestCase):
    def test_guess(self):
        cases = {
            "courses": "groceries", "Courses marché": "groceries", "boulangerie": "bakery",
            "resto en terrasse": "eating out", "pharmacie": "health", "parking": "transport",
            "abonnement netflix": "subscriptions", "cinéma": "leisure", "uber eats": "eating out",
            "lignes d'azur": "transport", "truc": UNCATEGORIZED, "": UNCATEGORIZED, None: UNCATEGORIZED,
        }
        for text, category in cases.items():
            self.assertEqual(guess_category(text), category, text)

    def test_stored_category_wins(self):
        e = Expense(source="telegram", chat_id=1, message_id=1, kind="text",
                    original_date="2026-10-01T00:00:00+00:00", author="alex", payer="alex",
                    description="resto", category="gifts")
        self.assertEqual(category_of(e), "gifts")


if __name__ == "__main__":
    unittest.main()
