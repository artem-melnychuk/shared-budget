"""Command line: `python -m budget import-export path/to/result.json`."""

import argparse
import os
import sys

from budget.chat_export import DEFAULT_TZ, load_export
from budget.ingest import import_export
from budget.members import Members
from budget.storage import Store


def read_env_file(path: str) -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments skipped. Real env vars win."""
    values = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip('"').strip("'")
    return {**values, **os.environ}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m budget")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-export", help="import a Telegram Desktop chat export (result.json)")
    imp.add_argument("result_json")
    imp.add_argument("--env", default=".env")
    args = parser.parse_args(argv)

    env = read_env_file(args.env)
    members = Members.from_env(env)
    if not any(m.telegram_ids or m.names for m in members.members):
        print("No members configured: set MEMBER_1_* and MEMBER_2_* in .env", file=sys.stderr)
        return 2
    db_path = env.get("BUDGET_DB") or "data/budget.db"
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    store = Store(db_path)
    try:
        s = import_export(store, members, load_export(args.result_json),
                          tz_name=env.get("BUDGET_TZ") or DEFAULT_TZ)
    finally:
        store.close()
    print(f"added {s.added}, duplicates {s.duplicate}, ignored {s.ignored}")
    for reason, count in sorted(s.reasons.items()):
        print(f"  {count} ignored: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
