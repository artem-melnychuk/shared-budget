import unittest

from budget import texts
from budget.categories import KEYWORDS, UNCATEGORIZED, category_of, guess_category, normalize
from budget.storage import Expense


class GuessCategoryTest(unittest.TestCase):
    def check(self, cases):
        for text, category in cases.items():
            self.assertEqual(guess_category(text), category, text)

    def test_french_chains(self):
        self.check({
            "Carrefour Market": "groceries", "carrefour city": "groceries", "MONOPRIX": "groceries",
            "monop'": "groceries", "Franprix": "groceries", "Lidl": "groceries", "Aldi": "groceries",
            "Picard surgelés": "groceries", "Intermarché": "groceries", "Super U": "groceries",
            "E.Leclerc": "groceries", "Auchan": "groceries", "Biocoop": "groceries",
            "Grand Frais": "groceries", "Géant Casino": "groceries",
            "SNCF": "transport", "TER Nice-Cannes": "transport", "Ouigo": "transport",
            "lignes d'azur": "transport", "Lignes d’Azur": "transport", "TotalEnergies": "transport",
            "péage Vinci": "transport", "Indigo parking": "transport",
            "Leroy Merlin": "home", "IKEA": "home", "EDF": "home",
            "Free mobile": "subscriptions", "Netflix": "subscriptions", "Bouygues": "subscriptions",
            "Fnac": "electronics", "Darty": "electronics", "Boulanger": "electronics",
            "Sephora": "beauty", "Nocibé": "beauty", "Decathlon": "clothes", "H&M": "clothes",
            "Pull & Bear": "clothes", "Pathé": "leisure", "Basic-Fit": "leisure",
            "Maxi Zoo": "pets",
        })

    def test_everyday_words(self):
        self.check({
            "courses": "groceries", "Courses marché": "groceries", "boulangerie": "bakery",
            "Boulangerie Paul": "bakery", "baguette": "bakery", "resto en terrasse": "eating out",
            "pharmacie": "health", "Pharmacie de la gare": "health", "médecin": "health",
            "parking": "transport", "abonnement netflix": "subscriptions", "cinéma": "leisure",
            "socca": "eating out", "café": "eating out", "coiffeur": "beauty", "vétérinaire": "pets",
        })

    def test_delivery(self):
        self.check({"uber eats": "delivery", "Deliveroo pizza": "delivery", "Just Eat": "delivery",
                    "livraison": "delivery", "uber": "transport"})

    def test_russian(self):
        self.check({"продукты": "groceries", "Аптека": "health", "такси": "transport",
                    "доставка": "delivery", "кафе": "eating out", "хлеб": "bakery", "стрижка": "beauty"})

    def test_whole_words_dont_leak(self):
        self.check({"barbier": "beauty", "bar à vin": "eating out", "business class": UNCATEGORIZED,
                    "cafetière": UNCATEGORIZED, "oranges": UNCATEGORIZED, "gazole": "transport",
                    "gaz": "home", "truc": UNCATEGORIZED, "": UNCATEGORIZED, None: UNCATEGORIZED})

    def test_normalize(self):
        self.assertEqual(normalize("  Lignes d’Azur  "), "lignes d azur")
        self.assertEqual(normalize("Pull & Bear"), "pull and bear")
        self.assertEqual(normalize("H&M"), "h&m")
        self.assertEqual(normalize("Épicerie"), "epicerie")

    def test_every_category_has_a_label(self):
        for key in [*KEYWORDS, UNCATEGORIZED]:
            self.assertIn(key, texts.CATEGORY_LABELS)

    def test_stored_category_wins(self):
        e = Expense(source="telegram", chat_id=1, message_id=1, kind="text",
                    original_date="2026-10-01T00:00:00+00:00", author="alex", payer="alex",
                    description="resto", category="gifts")
        self.assertEqual(category_of(e), "gifts")


if __name__ == "__main__":
    unittest.main()
