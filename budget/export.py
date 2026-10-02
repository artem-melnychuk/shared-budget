"""Expenses as CSV for Excel and Power BI.

Default flavour suits Excel in France: `;` between fields, decimal comma,
UTF-8 with a BOM so Excel detects the encoding. `plain=True` gives `,` and a
decimal point, for Power BI, pandas and the like. `amount_cents` is always
there as a locale-proof integer.
"""

import csv
from collections.abc import Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from budget.balance import SplitRule
from budget.categories import category_of
from budget.members import Members
from budget.storage import Expense

# Spreadsheets run cells starting with these as formulas.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe(text: str | None) -> str:
    text = text or ""
    return "'" + text if text.startswith(_FORMULA_START) else text


def _decimal(cents: int | None, comma: bool) -> str:
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}{',' if comma else '.'}{cents % 100:02d}"


def header(rule: SplitRule) -> list[str]:
    return ["id", "date", "time", "month", "type", "amount", "amount_cents", "currency",
            "payer", "payer_name", "paid_to", "shared", "category", "description",
            *(f"share_{k}" for k in rule.members),
            "author", "source", "kind", "payer_confirmed"]


def rows(expenses: Iterable[Expense], members: Members, rule: SplitRule,
         tz_name: str, comma: bool) -> Iterable[list[str]]:
    tz = ZoneInfo(tz_name)
    for e in expenses:
        when = datetime.fromisoformat(e.original_date).astimezone(tz)
        if e.is_reimbursement:
            kind, shares = "reimbursement", {}
        else:
            kind = "expense"
            if e.amount_cents is None:
                shares = {}
            elif e.is_shared:
                shares = rule.shares(e.amount_cents)
            else:
                shares = {k: e.amount_cents if k == e.payer else 0 for k in rule.members}
        yield [
            str(e.id), when.strftime("%Y-%m-%d"), when.strftime("%H:%M"), when.strftime("%Y-%m"),
            kind, _decimal(e.amount_cents, comma),
            "" if e.amount_cents is None else str(e.amount_cents), e.currency,
            e.payer or "", _safe(members.display(e.payer) if e.payer else ""), e.paid_to or "",
            "" if e.is_reimbursement else ("yes" if e.is_shared else "no"),
            "" if e.is_reimbursement else category_of(e), _safe(e.description),
            *(_decimal(shares.get(k), comma) if shares else "" for k in rule.members),
            e.author or "", e.source, e.kind, "yes" if e.payer_confirmed else "no",
        ]


def write_csv(out, expenses: Iterable[Expense], members: Members, rule: SplitRule,
              tz_name: str, plain: bool = False) -> int:
    """Write to an open text file (newline=""); return the number of expenses."""
    if not plain:
        out.write("﻿")
    writer = csv.writer(out, delimiter="," if plain else ";", lineterminator="\r\n")
    writer.writerow(header(rule))
    count = 0
    for row in rows(expenses, members, rule, tz_name, comma=not plain):
        writer.writerow(row)
        count += 1
    return count
