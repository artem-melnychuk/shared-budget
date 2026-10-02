"""Who paid what and who owes whom.

The split rule is a parameter, never stored: the same log can be re-read with
50/50 today and 60/40 tomorrow.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from budget.storage import Expense


@dataclass(frozen=True)
class SplitRule:
    """Weights per member key, e.g. {"alex": 60, "sam": 40}."""
    weights: dict[str, int]

    def __post_init__(self):
        if not self.weights or any(w < 0 for w in self.weights.values()) \
                or sum(self.weights.values()) <= 0:
            raise ValueError("split weights must be non-negative and not all zero")

    @classmethod
    def even(cls, keys: Sequence[str]) -> "SplitRule":
        return cls({k: 1 for k in keys})

    @classmethod
    def parse(cls, spec: str | None, keys: Sequence[str]) -> "SplitRule":
        """`None`, `50/50`, `60/40` or `60:40`, in member order (MEMBER_1, MEMBER_2...)."""
        if not spec:
            return cls.even(keys)
        parts = spec.replace(":", "/").split("/")
        if len(parts) != len(keys):
            raise ValueError(f"split {spec!r} needs {len(keys)} parts, one per member")
        try:
            weights = [int(p.strip()) for p in parts]
        except ValueError:
            raise ValueError(f"split {spec!r} must be whole numbers like 60/40") from None
        return cls(dict(zip(keys, weights)))

    @property
    def members(self) -> list[str]:
        return list(self.weights)

    def shares(self, amount_cents: int) -> dict[str, int]:
        """Split an amount in whole cents that add up exactly.

        Largest remainder method; a tie for a leftover cent goes to the member
        listed first, so the result is deterministic.
        """
        total = sum(self.weights.values())
        exact = {k: amount_cents * w for k, w in self.weights.items()}
        shares = {k: v // total for k, v in exact.items()}
        left = amount_cents - sum(shares.values())
        order = sorted(self.weights, key=lambda k: (-(exact[k] % total), self.members.index(k)))
        for k in order[:left]:
            shares[k] += 1
        return shares

    def describe(self) -> str:
        return "/".join(str(w) for w in self.weights.values())


@dataclass
class MemberTotals:
    paid_shared: int = 0     # shared expenses this member paid for
    paid_personal: int = 0   # personal expenses this member paid for
    share: int = 0           # this member's part of all shared expenses

    @property
    def paid(self) -> int:
        return self.paid_shared + self.paid_personal

    @property
    def net(self) -> int:
        """Positive: the others owe this member. Negative: this member owes."""
        return self.paid_shared - self.share

    @property
    def spent(self) -> int:
        """What this member consumed: their share of shared plus their personal."""
        return self.share + self.paid_personal


@dataclass(frozen=True)
class Debt:
    debtor: str
    creditor: str
    amount_cents: int


@dataclass
class Balance:
    rule: SplitRule
    currency: str
    members: dict[str, MemberTotals]
    counted: list[Expense] = field(default_factory=list)
    without_amount: list[Expense] = field(default_factory=list)
    without_payer: list[Expense] = field(default_factory=list)
    other_currency: list[Expense] = field(default_factory=list)

    @property
    def shared_total(self) -> int:
        return sum(m.paid_shared for m in self.members.values())

    @property
    def personal_total(self) -> int:
        return sum(m.paid_personal for m in self.members.values())

    @property
    def debts(self) -> list[Debt]:
        return settle({k: m.net for k, m in self.members.items()})


def settle(nets: dict[str, int]) -> list[Debt]:
    """Fewest transfers that clear the nets (greedy; exact for two members)."""
    debtors = sorted(([-v, k] for k, v in nets.items() if v < 0), key=lambda d: -d[0])
    creditors = sorted(([v, k] for k, v in nets.items() if v > 0), key=lambda c: -c[0])
    debts = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][0], creditors[j][0])
        debts.append(Debt(debtors[i][1], creditors[j][1], amount))
        debtors[i][0] -= amount
        creditors[j][0] -= amount
        if debtors[i][0] == 0:
            i += 1
        if creditors[j][0] == 0:
            j += 1
    return debts


def compute_balance(expenses: Iterable[Expense], rule: SplitRule, currency: str = "EUR") -> Balance:
    """Totals and net position per member.

    Skipped and counted separately: expenses without an amount (receipt not
    recognised yet), without a payer who is a member, or in another currency.
    """
    balance = Balance(rule, currency, {k: MemberTotals() for k in rule.members})
    for e in expenses:
        if e.amount_cents is None:
            balance.without_amount.append(e)
        elif e.payer not in balance.members:
            balance.without_payer.append(e)
        elif e.currency != currency:
            balance.other_currency.append(e)
        else:
            balance.counted.append(e)
            payer = balance.members[e.payer]
            if e.is_shared:
                payer.paid_shared += e.amount_cents
                for k, part in rule.shares(e.amount_cents).items():
                    balance.members[k].share += part
            else:
                payer.paid_personal += e.amount_cents
    return balance
