"""Quick text expenses: `12.50 boulangerie`, `35 courses`, `boulangerie 4,20€`."""

import re
from dataclasses import dataclass

# 1 to 5 integer digits keeps phone numbers and dates out; 1 or 2 decimals.
_AMOUNT = r"(?P<int>\d{1,5})(?:[.,](?P<dec>\d{1,2}))?"
_CURRENCY = r"(?:€|eur\b|euros?\b)"

# Amount first: "12.50 boulangerie", "€12,50 courses", "12.50€ courses", "35".
_LEADING = re.compile(
    rf"^\s*(?:€\s*)?{_AMOUNT}\s*{_CURRENCY}?(?:\s+(?P<desc>.*?))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
# Amount last only with a currency mark, so "see you at 7" stays a chat message.
_TRAILING = re.compile(
    rf"^\s*(?P<desc>.*?\S)\s+{_AMOUNT}\s*{_CURRENCY}\s*$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class TextExpense:
    amount_cents: int
    description: str


def parse_text_expense(text: str | None) -> TextExpense | None:
    """Return the amount and description, or None when the text isn't an expense."""
    if not text:
        return None
    match = _LEADING.match(text) or _TRAILING.match(text)
    if not match:
        return None
    dec = match["dec"] or ""
    cents = int(match["int"]) * 100 + int(dec.ljust(2, "0") or 0)
    if cents <= 0:
        return None
    return TextExpense(cents, (match["desc"] or "").strip())
