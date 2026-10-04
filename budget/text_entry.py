"""Quick text expenses: `12.50 boulangerie`, `35 courses`, `boulangerie 4,20€`.

A debt paid back is a text too: `remboursé 32`, `вернул 32`, `32 remboursement`.
A date may close the text: `12.50 boulangerie 01.10`, `5 café 01.10.2025`, `5 café вчера`.
"""

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta

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
    day: date | None = None      # a date written in the text, if any


# dd.mm or dd/mm, optionally with the year (same separator), or a relative word.
_DATE_WORDS = {"вчера": 1, "позавчера": 2, "hier": 1, "avant-hier": 2}
_DATE = (r"(?:(?P<d>\d{1,2})(?P<sep>[./])(?P<m>\d{1,2})(?:(?P=sep)(?P<y>\d{4}|\d{2}))?"
         r"|(?P<word>позавчера|вчера|avant-hier|hier))")
_TRAILING_DATE = re.compile(rf"^(?P<rest>.*?\S)\s+{_DATE}\s*$", re.IGNORECASE | re.DOTALL)
_DATE_ONLY = re.compile(rf"^\s*{_DATE}\s*$", re.IGNORECASE)


def _day(match, sent: date) -> date | None:
    """The calendar day a date token means, seen from the day the message was sent."""
    if match["word"]:
        return sent - timedelta(days=_DATE_WORDS[match["word"].lower()])
    d, m = int(match["d"]), int(match["m"])
    try:
        if match["y"]:
            year = int(match["y"])
            return date(year + 2000 if year < 100 else year, m, d)
        day = date(sent.year, m, d)
        # Without a year the date is never in the future: "28.12" sent on 3 January is last December.
        return day if day <= sent else date(sent.year - 1, m, d)
    except ValueError:
        return None


def parse_date_only(text: str | None, sent: date) -> date | None:
    """A text that is only a date and can't be read as an amount: `01/10`, `01.10.2026`, `вчера`.

    `01.10` is not one: on its own it reads as 1,10 €.
    """
    match = _DATE_ONLY.match(text or "")
    if not match or (match["sep"] == "." and not match["y"]):
        return None
    return _day(match, sent)


def _cents(match) -> int:
    return int(match["int"]) * 100 + int((match["dec"] or "").ljust(2, "0"))


def parse_text_expense(text: str | None, sent: date | None = None) -> TextExpense | None:
    """Return the amount and description, or None when the text isn't an expense.

    With `sent` (the local day the message was sent) a date at the end of the
    text is read too and returned as `day`; it only counts when what comes
    before it is an expense on its own, so a bare `12.10` stays 12,10 €.
    """
    if not text:
        return None
    if sent is not None and (match := _TRAILING_DATE.match(text)):
        day = _day(match, sent)
        if day is not None and (parsed := _parse(match["rest"])) is not None:
            return replace(parsed, day=day)
    return _parse(text)


def _parse(text: str) -> TextExpense | None:
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
