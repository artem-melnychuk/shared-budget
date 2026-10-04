"""Monthly report: by category, by member, and who owes whom."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from budget.balance import Balance, SplitRule, compute_balance
from budget.categories import category_of
from budget.savings import Savings, analyze
from budget.storage import Store

DEFAULT_TZ = "Europe/Paris"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_month(text: str) -> date:
    """`2026-10` -> date(2026, 10, 1)."""
    try:
        return datetime.strptime(text, "%Y-%m").date()
    except ValueError:
        raise ValueError(f"month {text!r} must look like 2026-10") from None


def parse_period(args: list[str]) -> tuple[date, date]:
    """`2026-10` -> one month; `2026-08 2026-10` or `2026-08..2026-10` -> a range, either order."""
    parts = " ".join(args).replace("..", " ").split()
    if len(parts) not in (1, 2):
        raise ValueError("a period is one month or two: 2026-08 2026-10")
    months = sorted(parse_month(p) for p in parts)
    return months[0], months[-1]


def months_between(first: date, last: date) -> list[date]:
    """Every month from `first` to `last`, both included."""
    months, m = [], first.replace(day=1)
    while m <= last:
        months.append(m)
        m = date(m.year + m.month // 12, m.month % 12 + 1, 1)
    return months


def month_bounds(month: date, tz_name: str = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """Start and end of a calendar month in local time, as UTC datetimes."""
    tz = ZoneInfo(tz_name)
    start = datetime(month.year, month.month, 1, tzinfo=tz)
    end = datetime(month.year + month.month // 12, month.month % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@dataclass
class CategoryLine:
    shared: int = 0
    personal: int = 0
    spent_by: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    paid_by: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # who actually paid

    @property
    def total(self) -> int:
        return self.shared + self.personal


@dataclass
class MonthReport:
    month: date
    month_balance: Balance
    running_balance: Balance        # everything up to the end of the month
    categories: dict[str, CategoryLine]
    tz_name: str = DEFAULT_TZ
    savings: Savings | None = None
    last_month: date | None = None       # set for a report over several months
    paid_by_month: dict[date, dict[str, int]] = field(default_factory=dict)

    @property
    def rule(self) -> SplitRule:
        return self.month_balance.rule

    @property
    def is_range(self) -> bool:
        return self.last_month is not None and self.last_month != self.month

    @property
    def months(self) -> list[date]:
        return months_between(self.month, self.last_month or self.month)


def build_report(store: Store, month: date, rule: SplitRule,
                 tz_name: str = DEFAULT_TZ, currency: str = "EUR",
                 last_month: date | None = None) -> MonthReport:
    """One month, or every month from `month` to `last_month` together.

    `month_balance` then covers the whole period. The "where to save" block is
    about one month (it compares with the month before), so a range has none.
    """
    last = last_month or month
    start, end = month_bounds(month, tz_name)[0], month_bounds(last, tz_name)[1]
    month_balance = compute_balance(store.between(start, end), rule, currency)
    running = compute_balance(store.between(EPOCH, end), rule, currency)

    tz = ZoneInfo(tz_name)
    categories: dict[str, CategoryLine] = defaultdict(CategoryLine)
    paid_by_month: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in month_balance.counted:
        local_month = datetime.fromisoformat(e.original_date).astimezone(tz).date().replace(day=1)
        paid_by_month[local_month][e.payer] += e.amount_cents
        line = categories[category_of(e)]
        line.paid_by[e.payer] += e.amount_cents
        if e.is_shared:
            line.shared += e.amount_cents
            for k, part in rule.shares(e.amount_cents).items():
                line.spent_by[k] += part
        else:
            line.personal += e.amount_cents
            line.spent_by[e.payer] += e.amount_cents
    ordered = dict(sorted(categories.items(), key=lambda kv: (-kv[1].total, kv[0])))
    savings = analyze(store, month, rule, tz_name, currency) if last == month else None
    return MonthReport(month, month_balance, running, ordered, tz_name, savings,
                       last_month=last, paid_by_month=dict(paid_by_month))


def money(cents: int, currency: str = "EUR") -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    symbol = "€" if currency == "EUR" else currency
    return f"{sign}{cents // 100}.{cents % 100:02d} {symbol}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]

    def fmt(r):
        return "  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths)))
    return [fmt(header), "  ".join("-" * w for w in widths), *(fmt(r) for r in rows)]


def _debts(balance: Balance) -> list[str]:
    debts = balance.debts
    if not debts:
        return ["  settled: nobody owes anything"]
    return [f"  {d.debtor} owes {d.creditor} {money(d.amount_cents, balance.currency)}" for d in debts]


def _skipped(balance: Balance) -> list[str]:
    lines = []
    if balance.without_amount:
        lines.append(f"  {len(balance.without_amount)} without amount (receipt not recognised yet)")
    if balance.without_payer:
        lines.append(f"  {len(balance.without_payer)} without a payer who is a member")
    if balance.other_currency:
        lines.append(f"  {len(balance.other_currency)} in a currency other than {balance.currency}")
    return lines


def _percent(share: float) -> str:
    return f"{share * 100:.0f}%"


def _savings(s: Savings | None, cur: str) -> list[str]:
    from budget import savings as rules

    if s is None or s.empty:
        return ["  nothing stands out"]
    out = []
    if s.recurring:
        out.append(f"  Recurring (same amount, same seller, {rules.RECURRING_MONTHS} months in a row):")
        out += [f"    {r.seller}: {money(r.amount_cents, cur)} a month, {money(r.yearly_cents, cur)} a year"
                for r in s.recurring]
    if s.small:
        out.append(f"  Frequent small spending (at least {rules.SMALL_MIN_COUNT} times up to "
                   f"{money(rules.SMALL_LIMIT_CENTS, cur)}):")
        out += [f"    {x.category}: {x.count} times, {money(x.total_cents, cur)}" for x in s.small]
    e = s.eating
    if e and e.eating_cents:
        parts = ", ".join(f"{c} {money(v, cur)}" for c, v in e.by_category.items() if v)
        line = f"  Delivery and eating out: {money(e.eating_cents, cur)} ({parts}), {_percent(e.share)} of spending"
        if e.previous_share is not None:
            line += f"; previous month {_percent(e.previous_share)}"
        out.append(line)
    return out


def render(report: MonthReport) -> str:
    b = report.month_balance
    cur = b.currency
    keys = report.rule.members
    m = lambda c: money(c, cur)  # noqa: E731
    out = [
        f"Report {report.month:%Y-%m} (split {report.rule.describe()} between {', '.join(keys)})",
        "",
        f"Counted: {len(b.counted)} expenses, {m(b.shared_total + b.personal_total)}"
        f" (shared {m(b.shared_total)}, personal {m(b.personal_total)})",
    ]
    skipped = _skipped(b)
    if skipped:
        out += ["Not counted:", *skipped]

    out += ["", "By member"]
    header = ["member", "paid", "paid shared", "paid personal", "share of shared", "spent"]
    rows = [[k, m(t.paid), m(t.paid_shared), m(t.paid_personal), m(t.share), m(t.spent)]
            for k, t in b.members.items()]
    if b.reimbursements:
        header += ["paid back", "got back"]
        for row, t in zip(rows, b.members.values()):
            row += [m(t.sent), m(t.received)]
    header.append("net")
    for row, t in zip(rows, b.members.values()):
        row.append(m(t.net))
    out += _table(header, rows)

    out += ["", "By category (spent = share of shared + own personal)"]
    if report.categories:
        rows = [[name, m(line.total), m(line.shared), m(line.personal), *(m(line.spent_by[k]) for k in keys)]
                for name, line in report.categories.items()]
        out += _table(["category", "total", "shared", "personal", *(f"{k} spent" for k in keys)], rows)
    else:
        out.append("  nothing this month")

    if b.reimbursements:
        tz = ZoneInfo(report.tz_name)
        out += ["", "Reimbursements"]
        for e in b.reimbursements:
            when = datetime.fromisoformat(e.original_date).astimezone(tz)
            note = f" ({e.description})" if e.description else ""
            out.append(f"  {when:%Y-%m-%d} {e.payer} paid back {e.paid_to} {m(e.amount_cents)}{note}")

    out += ["", "Where to save", *_savings(report.savings, cur)]

    out += ["", "Who owes whom, this month:", *_debts(b)]
    out += [f"Who owes whom, everything up to the end of {report.month:%Y-%m}:", *_debts(report.running_balance)]
    skipped = _skipped(report.running_balance)
    if skipped:
        out += ["  not counted in that total:", *("  " + s for s in skipped)]
    return "\n".join(out) + "\n"
