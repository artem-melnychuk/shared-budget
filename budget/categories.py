"""Categories for reports.

A category set by a person (`expenses.category`) wins. Otherwise it is guessed
from the description at report time, so improving these rules re-sorts old
expenses without touching stored data.
"""

from budget.storage import Expense

UNCATEGORIZED = "other"

# Lowercase word prefixes, checked against each word of the description.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "groceries": ("courses", "supermarch", "marché", "marche", "épicerie", "epicerie",
                  "carrefour", "monoprix", "lidl", "intermarch", "casino", "franprix",
                  "picard", "biocoop", "fromager", "primeur", "groceries"),
    "bakery": ("boulangerie", "pain", "baguette", "croissant", "pâtisserie", "patisserie"),
    "eating out": ("resto", "restaurant", "café", "cafe", "bar", "pizza", "kebab",
                   "sushi", "brasserie", "glace", "livraison", "uber eats", "deliveroo"),
    "transport": ("essence", "carburant", "parking", "péage", "peage", "bus", "tram",
                  "train", "sncf", "lignes d'azur", "taxi", "uber", "vélo", "velo"),
    "home": ("loyer", "edf", "électricité", "electricite", "eau", "gaz", "internet",
             "box", "ikea", "leroy", "bricolage", "ménage", "menage"),
    "health": ("pharmacie", "médecin", "medecin", "docteur", "dentiste", "mutuelle",
               "kiné", "kine", "opticien"),
    "subscriptions": ("abonnement", "netflix", "spotify", "deezer", "forfait", "mobile",
                      "téléphone", "telephone", "cloud"),
    "leisure": ("cinéma", "cinema", "musée", "musee", "concert", "théâtre", "theatre",
                "livre", "librairie", "sport", "piscine", "vacances", "hôtel", "hotel"),
    "clothes": ("vêtement", "vetement", "chaussure", "zara", "h&m", "decathlon"),
}


def guess_category(description: str | None) -> str:
    if not description:
        return UNCATEGORIZED
    text = description.casefold()
    # Multi-word keywords first, then single words by prefix.
    for category, words in KEYWORDS.items():
        if any(" " in w and w in text for w in words):
            return category
    tokens = text.replace("'", " ").replace(",", " ").split()
    for category, words in KEYWORDS.items():
        if any(tok.startswith(w) for tok in tokens for w in words if " " not in w):
            return category
    return UNCATEGORIZED


def category_of(expense: Expense) -> str:
    return expense.category or guess_category(expense.description)
