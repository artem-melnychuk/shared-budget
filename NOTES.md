# Notes

Decisions made while working, newest first.

## 2026-10-02: balance and monthly report

Modules: `budget/balance.py` (split rule, balance, settlement), `budget/categories.py`, `budget/report.py`; command `python -m budget report --month 2026-10 [--split 60/40]`.

Decisions:
- **Split rule** is a parameter (`SplitRule`), never stored: weights per member key. `--split 60/40` (or `BUDGET_SPLIT` in `.env`) gives weights in member order (MEMBER_1, MEMBER_2); default even. Shares are whole cents that add up to the amount exactly (largest remainder; a tie for the leftover cent goes to the first member).
- **Balance**: per member `paid_shared`, `paid_personal`, `share` (their part of every shared expense), `net = paid_shared - share` (positive = is owed), `spent = share + personal`. Personal expenses appear in totals but never create debt. Debts come from a greedy settlement of the nets (exact for two people, works for more).
- **Not counted, shown as counters**: no amount (receipt not recognised yet), payer missing or not a configured member key, currency other than the report's (`--currency`, default EUR). No conversion between currencies.
- **Month** is a calendar month in local time (`BUDGET_TZ`, default Europe/Paris), so 23:30 UTC on 31 Oct counts in November. The report shows the month's balance and the running balance of everything up to the end of the month. Reimbursements/settle-ups aren't modelled yet, so the running balance only grows until they are (Spliit's `isReimbursement` is the model to copy).
- **Categories**: new nullable `expenses.category` column for a category chosen by a person (`Store.set_category`); old databases get it via `ALTER TABLE` on open. When it's empty the report guesses from the description with French keyword prefixes (`budget/categories.py`), at report time, so better rules re-sort old expenses without touching stored data. Fallback category `other`.
- **Report language**: English for now, like the code; the bot's language is still an open question.
- Added `Store.set_amount` so a recognised amount can be filled in later (tests use it).

## 2026-10-02: first input layer (no live bot, no receipt recognition)

Modules in `budget/`: `telegram_update` (Bot API update JSON → `Incoming`), `chat_export` (Telegram Desktop `result.json` → `Incoming`), `members` (who is who), `text_entry` (`12.50 boulangerie`), `storage` (SQLite), `ingest` (glue + dedup), `__main__` (`python -m budget import-export result.json`). Standard library only, plus `tzdata` so `zoneinfo` works on Windows.

Decisions:
- **Members** come from env: `MEMBER_N_KEY` (stored in the DB, default `mN`), `MEMBER_N_TELEGRAM_ID` (comma-separated ids allowed), `MEMBER_N_NAMES` (display names for hidden forward authors). Id wins over name; names compare case- and whitespace-insensitively. A visible author whose id isn't configured also falls back to the name.
- **Who may write**: a Telegram update is ignored unless `from` (the sender/forwarder) is a member, so strangers can't fill the log. Export entries whose author isn't a member are skipped and counted.
- **Payer** defaults to the original author; if the author isn't a member (a shop's channel, an unknown hidden user), to the forwarder. `payer_confirmed = 0` until the bot asks. `is_shared` defaults to 1 (most things sent between them are joint); the bot will let them flip it. No split rule is stored.
- **Dates**: stored as ISO 8601 UTC strings. Forward → `forward_origin.date`; direct → `message.date`; export → `date_unixtime`, or `date` read as Europe/Paris (`BUDGET_TZ`) in old exports that lack it.
- **What is kept**: photos (largest `PhotoSize`), documents that are PDF or `image/*`, and text that parses as an amount. Photo/document captions are parsed too; the amount stays NULL when there is none (recognition comes later). Edits, stickers, voice, video, other files are skipped. Forwards from channels/groups use the channel title / signature as author name.
- **Text amounts**: amount first (`12.50 boulangerie`, `4,20€ café`, `€7 parking`, a bare `42`), or amount last only with a currency mark (`boulangerie 3,40€`), so `see you at 7` is not an expense. 1–5 integer digits, `.` or `,`, up to 2 decimals. Known false positive: `2 personnes ce soir` reads as 2 €; the payer/amount confirmation in the bot should catch it.
- **Dedup**, in order: same (source, chat, message id) — re-delivered update or re-imported export; same `file_unique_id`; same author + original date (to the second) + amount. The last one is what matches an export entry with a forward of the same message, and a text forwarded twice.
  Limitation: an export photo and a forward of the same photo don't match while their amount is unknown (the export has no `file_unique_id`). Once recognition fills `amount_cents`, rerun the author/date/amount check.
- **Albums**: each photo is its own row with the shared `media_group_id` (`Store.media_group()`); whether an album is one multi-page receipt or several receipts is left to the recognition step.
- `.env` is read by the CLI with a tiny parser (no python-dotenv); real env vars win.

## 2026-10-02: sandbox for autonomous work

Same scheme as `nice_events_sandbox`: the agent runs in Docker on a separate clone (branch `agent`), on an internal network whose only way out is a squid allowlist proxy. Differences: the `docker run` flags are written down in `.sandbox/compose.yaml`; `sandbox.ps1` drives it; `.gitattributes` forces LF and the container's git ignores file modes, so a Windows bind mount doesn't show every file as modified; dependencies install from the clone's `requirements.txt` at container start, so a new requirement doesn't need an image rebuild.
