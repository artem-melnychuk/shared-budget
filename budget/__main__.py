"""Command line.

    python -m budget import-export path/to/result.json
    python -m budget report --month 2026-10 [--split 60/40]
    python -m budget reimburse --from sam --to alex --amount 32.00 [--date 2026-10-31]
    python -m budget bot
    python -m budget export --month 2026-10 [--out file.csv] [--plain]
"""

import argparse
import logging
import os
import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

from budget.chat_export import DEFAULT_TZ, load_export
from budget.ingest import import_export
from budget.balance import SplitRule
from budget.members import Members
from budget.report import build_report, parse_month, render
from budget.storage import Store
from budget.text_entry import parse_amount


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


def _reimburse(args, env, members) -> int:
    keys = [m.key for m in members.members]
    tz = ZoneInfo(env.get("BUDGET_TZ") or DEFAULT_TZ)
    errors = []
    for who in (args.payer, args.paid_to):
        if who not in keys:
            errors.append(f"unknown member {who!r}; members are {', '.join(keys)}")
    if args.payer == args.paid_to:
        errors.append("--from and --to must be different members")
    amount = parse_amount(args.amount)
    if amount is None:
        errors.append(f"amount {args.amount!r} must look like 32 or 32.50")
    try:
        # A bare date means noon local time, safely inside that day and month.
        when = datetime.combine(datetime.strptime(args.date, "%Y-%m-%d").date(), time(12), tz) \
            if args.date else datetime.now(tz)
    except ValueError:
        errors.append(f"date {args.date!r} must look like 2026-10-31")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    db_path = env.get("BUDGET_DB") or "data/budget.db"
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    store = Store(db_path)
    try:
        store.add_reimbursement(args.payer, args.paid_to, amount, when,
                                currency=args.currency, description=args.note)
    finally:
        store.close()
    symbol = "€" if args.currency == "EUR" else args.currency
    print(f"recorded: {args.payer} paid back {args.paid_to} {amount // 100}.{amount % 100:02d} {symbol}"
          f" on {when:%Y-%m-%d}")
    return 0


def _bot(args, env, members) -> int:
    from budget.bot import Bot, run
    from budget.telegram_api import TelegramApi

    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set (see .env.example)", file=sys.stderr)
        return 2
    if not any(m.telegram_ids for m in members.members):
        print("No member Telegram ids: set MEMBER_1_TELEGRAM_ID and MEMBER_2_TELEGRAM_ID in .env",
              file=sys.stderr)
        return 2
    try:
        rule = SplitRule.parse(env.get("BUDGET_SPLIT"), [m.key for m in members.members])
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db_path = env.get("BUDGET_DB") or "data/budget.db"
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    store = Store(db_path)
    api = TelegramApi(token)
    bot = Bot(store, members, api, rule, tz_name=env.get("BUDGET_TZ") or DEFAULT_TZ)
    print("Bot is running; Ctrl+C to stop.")
    try:
        run(bot, api)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            bot.flush_all()
        except Exception:
            logging.exception("answering the last batch failed")
        store.close()
    return 0


def _export(args, env, members) -> int:
    from budget.export import write_csv
    from budget.report import month_bounds

    tz_name = env.get("BUDGET_TZ") or DEFAULT_TZ
    try:
        month = parse_month(args.month) if args.month else None
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
        expenses = store.between(*month_bounds(month, tz_name)) if month else store.all()
    finally:
        store.close()
    out_path = args.out or os.path.join(os.path.dirname(db_path) or ".",
                                        f"expenses-{month:%Y-%m}.csv" if month else "expenses-all.csv")
    if out_path == "-":
        write_csv(sys.stdout, expenses, members, rule, tz_name, plain=args.plain)
        return 0
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        count = write_csv(f, expenses, members, rule, tz_name, plain=args.plain)
    print(f"{count} rows written to {out_path}")
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
    reim = sub.add_parser("reimburse", help="record money one member paid back to the other")
    reim.add_argument("--from", dest="payer", required=True, help="member key who gave the money")
    reim.add_argument("--to", dest="paid_to", required=True, help="member key who received it")
    reim.add_argument("--amount", required=True, help="e.g. 32.50")
    reim.add_argument("--date", help="YYYY-MM-DD, default now")
    reim.add_argument("--note", help="optional, e.g. 'bank transfer'")
    reim.add_argument("--currency", default="EUR")
    bot = sub.add_parser("bot", help="run the Telegram bot (long polling)")
    exp = sub.add_parser("export", help="expenses as CSV for Excel / Power BI")
    exp.add_argument("--month", help="YYYY-MM; default everything")
    exp.add_argument("--out", help="file path, '-' for stdout; default next to the database")
    exp.add_argument("--plain", action="store_true",
                     help="',' separator and decimal point (Power BI, pandas) instead of Excel FR style")
    exp.add_argument("--split", help="weights for the share_* columns, e.g. 60/40")
    for p in (imp, rep, reim, bot, exp):
        p.add_argument("--env", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    env = read_env_file(args.env)
    members = Members.from_env(env)
    command = {"import-export": _import_export, "report": _report, "reimburse": _reimburse,
               "bot": _bot, "export": _export}[args.command]
    return command(args, env, members)


if __name__ == "__main__":
    sys.exit(main())
