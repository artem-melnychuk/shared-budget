# shared_budget

A Telegram bot that turns receipts (photos, e-receipts, quick text entries) into a shared expense log for two people: how much each of them spent, on what, in which category, month by month, and where the money could be saved. Personal project, free tools only. Work in progress: in daily use since 2026-10-04.

## Roadmap

Done:
- [x] Input from Telegram: forwarded messages keep their original author and date; direct texts like `12.50 boulangerie`, with an optional date at the end (`12.50 boulangerie 01.10`, `5 café вчера`); receipt photos and PDF/screenshot e-receipts.
- [x] Old history from a Telegram Desktop chat export (`import-export`), with the same dedup as live messages.
- [x] Expense cards with buttons: payer, shared or personal, category, transfer between the two, delete. Amount and date are fixed by replying to the card; a bare amount sent right after a receipt fills that receipt in.
- [x] `/balance` and `/report` (one month or several): who spent what, by category and by month. No "who owes whom": the owner's call.
- [x] Category rules for French shops; a "where to save" block (recurring payments, frequent small spending, eating out share).
- [x] CSV export for Excel and Power BI.
- [x] Docker sandbox for unattended agent work.
- [x] First live run, on the home PC (2026-10-04).

Next:
- [ ] Read receipts by itself: total, date, shop and line items from a photo; from the text layer of a PDF e-receipt. Free only: a local vision model or the Gemini free tier, not chosen yet.
- [ ] Line items in their own table, to compare the price of the same product across shops.
- [ ] A month-end summary that the bot sends on its own.
- [ ] Settle the thresholds of the "where to save" block (open questions in `NOTES.md`).

Later:
- [ ] Import the real chat history once recognition works.
- [ ] A group chat "both + the bot", so nothing has to be forwarded.
- [ ] Who paid, from the card's last 4 digits printed on the receipt.
- [ ] Run 24/7 on free hosting instead of the home PC.
- [ ] A Power BI dashboard over the CSV export.

## Develop

```powershell
python -m unittest discover -s tests
python -m budget import-export path\to\result.json   # backfill from a Telegram Desktop export
python -m budget report --month 2026-10 --split 60/40  # full report, incl. shares under a split rule
python -m budget reimburse --from m2 --to m1 --amount 32.50 --date 2026-10-31  # a debt paid back
python -m budget bot                                   # run the Telegram bot (needs TELEGRAM_BOT_TOKEN)
python -m budget export --month 2026-10                # CSV for Excel; --plain for Power BI
```

Members, database path and the default split come from `.env` (see `.env.example`).

## Autonomous development in Docker

Claude Code can work on this repo unattended inside a sandbox: a separate clone, no host credentials, internet only through an allowlist proxy.

```powershell
.\sandbox.ps1            # start the sandbox and open Claude Code
.\sandbox.ps1 check      # smoke test of the isolation
.\sandbox.ps1 review     # see what the agent committed on branch "agent"
.\sandbox.ps1 publish    # merge it into master after a y/N prompt and push to GitHub
```

The agent itself can't push: GitHub only gets what was reviewed on the host.

The first start asks you to sign in to Claude once; the login is kept in a Docker volume. See [CLAUDE.md](CLAUDE.md) for the project context and `.sandbox/` for the setup.
