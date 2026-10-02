"""Categories for reports.

A category set by a person (`expenses.category`) wins. Otherwise it is guessed
from the description at report time, so improving these rules re-sorts old
expenses without touching stored data.

Matching ignores case and accents. A keyword matches the start of a word
(`boulang` would match `boulangerie`), or the whole word when written with a
leading `=` (`=bar` doesn't match `barbier`). Keywords of several words match
as a phrase and are tried before single words, so `uber eats` wins over `=uber`.
When single words point to different categories, the one listed first below wins.
"""

import re
import unicodedata

from budget.storage import Expense

UNCATEGORIZED = "other"

KEYWORDS: dict[str, tuple[str, ...]] = {
    "delivery": (
        "uber eats", "ubereats", "deliveroo", "just eat", "justeat", "livraison repas",
        "livraison", "доставка",
    ),
    "groceries": (
        "courses", "supermarche", "hypermarche", "epicerie", "marche", "primeur", "fromagerie",
        "fromager", "boucherie", "boucher", "poissonnerie", "drive",
        "carrefour", "carrefour market", "carrefour city", "monoprix", "=monop", "franprix",
        "lidl", "aldi", "leader price", "intermarche", "super u", "hyper u", "u express",
        "=casino", "geant casino", "=spar", "vival", "picard", "biocoop", "naturalia",
        "la vie claire", "grand frais", "auchan", "leclerc", "=cora", "=netto", "=g20",
        "=proxi", "coccinelle", "la grande epicerie",
        "продукты", "супермаркет", "рынок", "овощи", "фрукты",
    ),
    "bakery": (
        "boulangerie", "=pain", "baguette", "croissant", "viennoiserie", "patisserie",
        "=paul", "marie blachere", "=feuillette",
        "булочная", "хлеб", "выпечка",
    ),
    "eating out": (
        "restaurant", "=resto", "brasserie", "bistrot", "bistro", "=cafe", "=bar", "pizzeria",
        "=pizza", "kebab", "sushi", "burger", "mcdo", "mcdonald", "burger king", "=kfc",
        "=quick", "=subway", "starbucks", "glacier", "=glace", "creperie", "=snack", "socca",
        "pan bagnat", "brunch", "dejeuner", "diner", "apero",
        "кафе", "ресторан", "обед", "ужин", "кофе", "=бар", "пицца",
    ),
    "transport": (
        "essence", "carburant", "gasoil", "gazole", "=diesel", "station service", "totalenergies",
        "=total", "=esso", "=shell", "=bp", "=avia", "parking", "=indigo", "peage", "autoroute",
        "=vinci", "=bus", "=tram", "lignes d azur", "lignes azur", "=sncf", "=ter", "=tgv",
        "inoui", "ouigo", "=train", "=taxi", "=uber", "=bolt", "=lime", "velo bleu", "=velo",
        "blablacar", "air france", "easyjet", "=vol", "aeroport", "=zou",
        "бензин", "заправка", "такси", "парковка", "поезд", "автобус", "трамвай", "транспорт",
        "проезд", "самолет",
    ),
    "home": (
        "=loyer", "charges", "=edf", "engie", "electricite", "=eau", "=gaz", "veolia",
        "internet", "=box", "ikea", "leroy merlin", "castorama", "bricorama", "=brico",
        "bricolage", "maisons du monde", "conforama", "=but", "=action", "=gifi",
        "foir fouille", "=hema", "assurance habitation", "menage", "quincaillerie", "pressing",
        "laverie",
        "аренда", "квартплата", "коммуналка", "электричество", "=свет", "хозтовары", "уборка",
    ),
    "health": (
        "pharmacie", "parapharmacie", "medecin", "docteur", "generaliste", "dentiste",
        "mutuelle", "=kine", "kinesitherapeute", "osteo", "opticien", "laboratoire", "=labo",
        "analyses", "hopital", "clinique", "ordonnance", "doctolib",
        "аптека", "врач", "лекарств", "стоматолог", "анализы",
    ),
    "subscriptions": (
        "abonnement", "netflix", "spotify", "deezer", "disney", "=canal", "amazon prime",
        "prime video", "youtube premium", "icloud", "google one", "chatgpt", "forfait",
        "free mobile", "=sfr", "red by sfr", "bouygues", "=orange", "=sosh", "b and you",
        "подписка", "=телефон", "мобильн", "=связь",
    ),
    "electronics": (
        "=fnac", "darty", "=boulanger", "apple store", "=ldlc", "cdiscount", "materiel informatique",
        "техника", "электроника",
    ),
    "clothes": (
        "vetement", "chaussure", "=zara", "h&m", "uniqlo", "kiabi", "primark", "=celio",
        "=jules", "galeries lafayette", "decathlon", "vinted", "=mango", "bershka",
        "pull and bear", "=pull",
        "одежда", "обувь",
    ),
    "beauty": (
        "coiffeur", "coiffure", "barbier", "sephora", "nocibe", "marionnaud", "yves rocher",
        "cosmetique", "manucure", "estheticienne",
        "парикмахер", "стрижка", "косметика", "маникюр",
    ),
    "leisure": (
        "cinema", "=pathe", "=ugc", "musee", "concert", "theatre", "spectacle", "=livre",
        "librairie", "=sport", "piscine", "salle de sport", "basic fit", "fitness", "vacances",
        "hotel", "airbnb", "booking", "voyage", "=plage", "=jeu", "steam", "playstation",
        "кино", "музей", "концерт", "театр", "книг", "отпуск", "отель", "спортзал",
    ),
    "pets": (
        "veterinaire", "=veto", "animalerie", "croquettes", "maxi zoo",
        "ветеринар", "=корм",
    ),
}


def normalize(text: str) -> str:
    """Lower case, no accents, punctuation as spaces (`&` kept for H&M)."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("&", " and ") if " & " in text else text
    return " ".join(re.sub(r"[^\w&]+", " ", text).split())


def _rules():
    phrases, exact, prefixes = [], {}, []
    for category, words in KEYWORDS.items():
        for word in words:
            whole = word.startswith("=")
            norm = normalize(word.lstrip("="))
            if " " in norm:
                phrases.append((f" {norm} ", category))
            elif whole:
                exact.setdefault(norm, category)
            else:
                prefixes.append((norm, category))
    return phrases, exact, prefixes


_PHRASES, _EXACT, _PREFIXES = _rules()
_ORDER = {c: i for i, c in enumerate(KEYWORDS)}


def guess_category(description: str | None) -> str:
    if not description:
        return UNCATEGORIZED
    text = normalize(description)
    padded = f" {text} "
    found = [c for phrase, c in _PHRASES if phrase in padded]
    if not found:
        for token in text.split():
            if token in _EXACT:
                found.append(_EXACT[token])
            found += [c for prefix, c in _PREFIXES if token.startswith(prefix)]
    return min(found, key=_ORDER.__getitem__) if found else UNCATEGORIZED


def category_of(expense: Expense) -> str:
    return expense.category or guess_category(expense.description)
