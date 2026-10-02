"""Command line.

    python -m budget import-export path/to/result.json
    python -m budget report --month 2026-10 [--split 60/40]
"""

import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from budget.chat_export import DEFAULT_TZ, load_export
from budget.ingest import import_export
from budget.balance import SplitRule
from budget.members import Members
from budget.report import build_report, parse_month, render
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


def _import_export(args, env, members) -> int:
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


def _report(args, env, members) -> int:
    tz_name = env.get("BUDGET_TZ") or DEFAULT_TZ
    try:
        month = parse_month(args.month) if args.month \
            else datetime.now(ZoneInfo(tz_name)).date().replace(day=1)
        rule = SplitRule.parse(args.split or env.get("BUDGET_SPLIT"), [m.key for m in members.members])
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    db_path = env.get("BUDGET_DB") or "data/budget.db"
    if not os.path.exists(db_path):
        print(f"No database at {db_path}", file=sys.stderr)
        return 2
    store = Store(db_path)
    try:
        report = build_report(store, month, rule, tz_name=tz_name, currency=args.currency)
    finally:
        store.close()
    sys.stdout.write(render(report))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m budget")
    parser.add_argument("--env", default=".env", help="env file (default .env); real env vars win")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-export", help="import a Telegram Desktop chat export (result.json)")
    imp.add_argument("result_json")
    rep = sub.add_parser("report", help="monthly report: categories, members, who owes whom")
    rep.add_argument("--month", help="YYYY-MM, default the current month")
    rep.add_argument("--split", help="weights in member order, e.g. 60/40 (default 50/50 or BUDGET_SPLIT)")
    rep.add_argument("--currency", default="EUR")
    for p in (imp, rep):
        p.add_argument("--env", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    env = read_env_file(args.env)
    members = Members.from_env(env)
    command = {"import-export": _import_export, "report": _report}[args.command]
    return command(args, env, members)


if __name__ == "__main__":
    sys.exit(main())
