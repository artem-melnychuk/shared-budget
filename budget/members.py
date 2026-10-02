"""The two members of the budget and how to recognise them.

Names and Telegram ids come from the environment (`.env`), never from code.
For member N (1 and 2):

    MEMBER_N_KEY          stable internal key stored in the database (default "mN")
    MEMBER_N_TELEGRAM_ID  numeric Telegram user id; several may be comma-separated
    MEMBER_N_NAMES        display names, comma-separated; used when Telegram hides
                          the author of a forwarded message, and as a fallback
"""

import os
from dataclasses import dataclass, field


def normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


@dataclass(frozen=True)
class Member:
    key: str
    telegram_ids: frozenset[int] = field(default_factory=frozenset)
    names: tuple[str, ...] = ()


class Members:
    def __init__(self, members: list[Member]):
        self.members = list(members)
        self._by_id: dict[int, Member] = {}
        self._by_name: dict[str, Member] = {}
        for member in self.members:
            for user_id in member.telegram_ids:
                self._by_id[user_id] = member
            for name in member.names:
                self._by_name[normalize_name(name)] = member

    @classmethod
    def from_env(cls, env=None, count: int = 2) -> "Members":
        env = os.environ if env is None else env
        members = []
        for n in range(1, count + 1):
            ids = env.get(f"MEMBER_{n}_TELEGRAM_ID", "")
            names = env.get(f"MEMBER_{n}_NAMES", "")
            members.append(Member(
                key=env.get(f"MEMBER_{n}_KEY") or f"m{n}",
                telegram_ids=frozenset(int(x) for x in ids.split(",") if x.strip()),
                names=tuple(x.strip() for x in names.split(",") if x.strip()),
            ))
        return cls(members)

    def by_user_id(self, user_id: int | None) -> Member | None:
        return self._by_id.get(user_id) if user_id is not None else None

    def by_name(self, name: str | None) -> Member | None:
        return self._by_name.get(normalize_name(name)) if name else None

    def resolve(self, user_id: int | None, name: str | None) -> Member | None:
        """User id wins; the display name is the fallback (hidden forward authors)."""
        return self.by_user_id(user_id) or self.by_name(name)
