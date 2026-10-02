"""Quick text expenses: `12.50 boulangerie`, `35 courses`, `boulangerie 4,20€`.

A debt paid back is a text too: `remboursé 32`, `вернул 32`, `32 remboursement`.
"""

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


# A payback: the word before or right after the amount.
_PAYBACK_WORD = r"(?:rembours\w*|remb\b\.?|вернул[аи]?|верну\b|возврат\w*|отдал[аи]?)"
_PAYBACK_FIRST = re.compile(
    rf"^\s*{_PAYBACK_WORD}(?:\s+(?:долг[аи]?|la dette))?\s*:?\s*(?:€\s*)?{_AMOUNT}\s*{_CURRENCY}?"
    rf"(?:\s+(?P<desc>.*?))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_PAYBACK_AFTER = re.compile(rf"^{_PAYBACK_WORD}(?:\s+(?:долг[аи]?|la dette))?\s*(?P<rest>.*)$",
                            re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class TextExpense:
    amount_cents: int
    description: str
    is_reimbursement: bool = False


def _cents(match) -> int:
    return int(match["int"]) * 100 + int((match["dec"] or "").ljust(2, "0"))


def parse_text_expense(text: str | None) -> TextExpense | None:
    """Return the amount and description, or None when the text isn't an expense."""
    if not text:
        return None
    if match := _PAYBACK_FIRST.match(text):
        cents = _cents(match)
        return TextExpense(cents, (match["desc"] or "").strip(), True) if cents > 0 else None
    match = _LEADING.match(text) or _TRAILING.match(text)
    if not match:
        return None
    cents = _cents(match)
    if cents <= 0:
        return None
    description = (match["desc"] or "").strip()
    if match.re is _LEADING and (payback := _PAYBACK_AFTER.match(description)):
        return TextExpense(cents, payback["rest"].strip(), True)
    return TextExpense(cents, description)


_PLAIN_AMOUNT = re.compile(rf"^\s*(?:€\s*)?{_AMOUNT}\s*{_CURRENCY}?\s*$", re.IGNORECASE)


def parse_amount(text: str | None) -> int | None:
    """`32`, `32.5`, `32,50 €` -> cents; None if it isn't a positive amount."""
    match = _PLAIN_AMOUNT.match(text or "")
    if not match:
        return None
    return _cents(match) or None
