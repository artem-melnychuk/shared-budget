# shared_budget

Shared-expense tracker for a couple living in Nice, France. Goal: see who pays for what, where the money goes by category, how much they spend together and each on their own, and where they could save.

This repo is public. Keep personal details (names, real amounts, shops, receipts) out of code, tests, docs and commit messages.

## Status

Empty skeleton (2026-10-02). There is no approved project plan yet: the decisions below are the starting point, not a spec. Build what the current task asks, not the whole idea.

## Decided (2026-10-01)

- Input channel: a Telegram bot. Both use Telegram; nothing extra to install.
- Payments: each pays with their own card, plus cash and online orders/subscriptions (receipts arrive by email). No joint account.
- Split rule: not decided. Store who paid and whether an expense is shared or personal; compute balances from a rule that can change later (start with 50/50). Don't bake the rule into stored data.
- Budget: free only. No paid API, no paid hosting, nothing that needs a credit card.
- Since 2023-08-01 French shops print a receipt only on request (AGEC law); many offer e-receipts by email, SMS or app instead. A receipt photo is therefore only one input: also PDFs/screenshots of e-receipts and quick text entries like `12.50 boulangerie`.

## Open questions (ask, don't decide silently)

- Receipt recognition: Gemini API free tier (Google uses free-tier request content to improve its products, so receipts would go to Google) vs a local model on the home PC (8 GB VRAM GPU) vs plain OCR plus rules.
- Where the bot runs 24/7 for free.
- Language of the bot's messages.

## Conventions

- Python 3.13, dependencies in `requirements.txt`, tests with `unittest` under `tests/`.
- Money as integer cents (`amount_cents`) with a currency code next to it; EUR by default.
- Tests run offline: fake Telegram updates, saved model responses, made-up receipts.
- Never commit real receipts, photos, bank exports, tokens, `.env` or `*.db`.
- Secrets come from environment variables (`.env`, see `.env.example`), never from code.
- Decisions made while working go into `NOTES.md` with a date.

```bash
python -m unittest discover -s tests
```

## Reference projects

Take ideas, not code wholesale; check the license first.

- [Spliit](https://github.com/spliit-app/spliit) (TypeScript): the data model is worth copying. `Expense` (amount in integer cents, `paidBy`, category, `isReimbursement`, `splitMode`) plus `ExpensePaidFor` (participant, shares); split modes `EVENLY` / `BY_SHARES` / `BY_PERCENTAGE` / `BY_AMOUNT`. Scans receipts through an OpenAI-compatible vision API.
- [borton](https://github.com/richardye101/borton) (JavaScript): Telegram photo, then Gemini vision, then a remembered map from card last-4 digits to the account that paid; a caption `split w <name>` splits 50/50.
- [tripsplitter](https://github.com/talkintomato/tripsplitter) (TypeScript, MIT): Telegram group bot that splits one receipt item by item.
- [TaxHacker](https://github.com/vas3k/TaxHacker) (MIT): LLM receipt parsing with line items and custom categories; no splitting between people.

## Telegram

- In a group chat a bot sees only commands and mentions unless privacy mode is off (BotFather `/setprivacy`) or the bot is an admin.

## Sandbox (autonomous work)

`sandbox.ps1` runs Claude Code with `--dangerously-skip-permissions` in Docker, on a separate clone `..\shared_budget_sandbox`, branch `agent`. The container has no host credentials, can't push, and reaches the internet only through a squid allowlist (`.sandbox/squid/squid.conf`). The agent's extra rules are in `.sandbox/agent-rules.md`. The agent commits on `agent` only; review, merge and push to GitHub happen on the host:

```powershell
.\sandbox.ps1 review     # what the agent committed
.\sandbox.ps1 publish    # merge agent into master after a y/N prompt, push to GitHub
```
