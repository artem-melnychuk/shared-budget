"""Where the month's money could be saved.

Three signals, each a simple rule on the counted expenses (amount known, not a
reimbursement, report currency), shared and personal alike:

- recurring payments: the same amount to the same seller in each of the last
  `RECURRING_MONTHS` months, ending with the report month (subscriptions);
- frequent small spending: at least `SMALL_MIN_COUNT` expenses of at most
  `SMALL_LIMIT_CENTS` in one category during the month;
- delivery and eating out: their total and share of the month's spending,
  next to the previous month's share.

The seller is the description, normalised (case, accents, punctuation).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from budget.balance import SplitRule, compute_balance
from budget.categories import category_of, normalize
from budget.storage import Expense, Store

RECURRING_MONTHS = 3
SMALL_LIMIT_CENTS = 1000
SMALL_MIN_COUNT = 8
EATING_CATEGORIES = ("delivery", "eating out")


@dataclass(frozen=True)
class Recurring:
    seller: str            # description as first written
    amount_cents: int
    months: int

    @property
    def yearly_cents(self) -> int:
        return self.amount_cents * 12


@dataclass(frozen=True)
class SmallSpending:
    category: str
    count: int
    total_cents: int


@dataclass
class EatingShare:
    by_category: dict[str, int]
    total_cents: int            # all counted spending this month
    previous_share: float | None

    @property
    def eating_cents(self) -> int:
        return sum(self.by_category.values())

    @property
    def share(self) -> float | None:
        return self.eating_cents / self.total_cents if self.total_cents else None


@dataclass
class Savings:
    recurring: list[Recurring] = field(default_factory=list)
    small: list[SmallSpending] = field(default_factory=list)
    eating: EatingShare | None = None

    @property
    def empty(self) -> bool:
        return not self.recurring and not self.small and not (self.eating and self.eating.eating_cents)


def _shift(month: date, months: int) -> date:
    index = month.year * 12 + month.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _local_month(e: Expense, tz: ZoneInfo) -> date:
    return datetime.fromisoformat(e.original_date).astimezone(tz).date().replace(day=1)


def analyze(store: Store, month: date, rule: SplitRule, tz_name: str, currency: str = "EUR") -> Savings:
    from budget.report import month_bounds  # report imports this module

    tz = ZoneInfo(tz_name)
    first = _shift(month, -(RECURRING_MONTHS - 1))
    start, _ = month_bounds(first, tz_name)
    _, end = month_bounds(month, tz_name)
    counted = compute_balance(store.between(start, end), rule, currency).counted
    by_month: dict[date, list[Expense]] = defaultdict(list)
    for e in counted:
        by_month[_local_month(e, tz)].append(e)
    this_month = by_month.get(month, [])

    # Recurring: (seller, amount) seen in every month of the window.
    seen: dict[tuple[str, int], set[date]] = defaultdict(set)
    names: dict[tuple[str, int], str] = {}
    for m, expenses in by_month.items():
        for e in expenses:
            seller = normalize(e.description or "")
            if seller:
                key = (seller, e.amount_cents)
                seen[key].add(m)
                if m == month or key not in names:
                    names[key] = e.description.strip()
    recurring = sorted(
        (Recurring(names[key], key[1], len(months)) for key, months in seen.items()
         if len(months) == RECURRING_MONTHS),
        key=lambda r: (-r.amount_cents, r.seller.casefold()))

    # Frequent small spending, per category.
    small_count: dict[str, int] = defaultdict(int)
    small_total: dict[str, int] = defaultdict(int)
    for e in this_month:
        if e.amount_cents <= SMALL_LIMIT_CENTS:
            category = category_of(e)
            small_count[category] += 1
            small_total[category] += e.amount_cents
    small = sorted((SmallSpending(c, n, small_total[c]) for c, n in small_count.items() if n >= SMALL_MIN_COUNT),
                   key=lambda s: (-s.total_cents, s.category))

    # Delivery and eating out.
    def eating(expenses):
        out = {c: 0 for c in EATING_CATEGORIES}
        for e in expenses:
            if (c := category_of(e)) in out:
                out[c] += e.amount_cents
        return out, sum(e.amount_cents for e in expenses)

    current, total = eating(this_month)
    prev_eating, prev_total = eating(by_month.get(_shift(month, -1), []))
    previous_share = sum(prev_eating.values()) / prev_total if prev_total else None
    return Savings(recurring, small, EatingShare(current, total, previous_share))
