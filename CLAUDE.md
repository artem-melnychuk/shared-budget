# shared_budget

Shared-expense tracker for a couple living in Nice, France. Goal: see who pays for what, where the money goes by category, how much they spend together and each on their own, and where they could save.

This repo is public. Keep personal details (names, real amounts, shops, receipts) out of code, tests, docs and commit messages.

## Status (end of 2026-10-02)

Built and covered by offline tests: the input layer (forwards, Telegram Desktop export, members, dedup), the SQLite store, balance with the split rule as a parameter, reimbursements, a monthly report with categories and a "where to save" block, CSV export for Excel/Power BI, and a long-polling bot (`python -m budget bot`) on a standard-library Bot API client. Decisions for each piece are in `NOTES.md`.

Not done yet: a first live run with a real bot token, receipt recognition (amounts for photos are typed in by hand for now), 24/7 hosting. There is no approved overall plan: build what the current task asks.

## Decided (2026-10-01)

- Input channel: a Telegram bot. Both use Telegram; nothing extra to install.
- Payments: each pays with their own card, plus cash and online orders/subscriptions (receipts arrive by email). No joint account.
- Split rule: not decided. Store who paid and whether an expense is shared or personal; compute balances from a rule that can change later (start with 50/50). Don't bake the rule into stored data.
- Budget: free only. No paid API, no paid hosting, nothing that needs a credit card.
- Since 2023-08-01 French shops print a receipt only on request (AGEC law); many offer e-receipts by email, SMS or app instead. A receipt photo is therefore only one input: also PDFs/screenshots of e-receipts and quick text entries like `12.50 boulangerie`.

## Open questions (ask, don't decide silently)

- Receipt recognition: Gemini API free tier (Google uses free-tier request content to improve its products, so receipts would go to Google) vs a local model on the home PC (8 GB VRAM GPU) vs plain OCR plus rules.
- Where the bot runs 24/7 for free.
- Thresholds of the "where to save" block: see "Open questions for the owner" in `NOTES.md`.

The bot speaks Russian; all its texts live in `budget/texts.py`.

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

## Input: how expenses reach the bot (decided 2026-10-02)

The two people already send each other receipts and notes in their private chat. A bot can't join a private 1:1 chat, so input comes three ways, all landing in the same expense log:

1. **Forwarded messages** (main path now). Either person selects messages in their private chat and forwards them to the bot, many at once; each arrives as its own update with its photo, document or text and caption.
   - The original author is in `message.forward_origin` (Bot API 7.0+): `MessageOriginUser` has `sender_user` (id + name); `MessageOriginHiddenUser` has only `sender_user_name`, a display-name string, when the author's Telegram privacy hides forwarded messages. Both carry `date`, the original send time; use it as the expense date, not the forward time.
   - Map authors to the two members by user id, falling back to a configured display name for hidden users. Names live in config or `.env`, never in code or fixtures.
   - A message with no `forward_origin` was written to the bot directly: its author is `message.from_user`.
2. **Telegram Desktop chat export** (one-off backfill of old history). Chat menu, Export chat history, format JSON: `result.json` plus `photos/` and `files/` folders. Each entry in `messages` has `from` (name), `from_id` (`"user<digits>"`), `date`, and `photo` or `file` as a relative path. `text` is either a string or a list of strings and entity objects, so flatten it. Skip `type == "service"` entries.
3. **A group "both of them + the bot"** (later, for new receipts). In a group a bot sees only commands, mentions and replies unless privacy mode is off (BotFather `/setprivacy`) or the bot is an admin. Author is `message.from_user`.

Rules for all three:
- Sender is not always payer: one person often photographs the other's receipt. Default payer = author, and the bot asks to confirm or change it with an inline button. Later, a card's last 4 digits printed on the receipt can map to its owner (as borton does).
- Deduplicate: the same receipt forwarded twice, or present in both an export and a forward, must count once. Key a photo on the `file_unique_id` of its largest `PhotoSize` (Telegram keeps it stable across forwards and bots; it can't be used to download). For a JSON export, which has no `file_unique_id`, fall back to author + original date + amount.
- Several photos sent together (an album) arrive as separate messages sharing a `media_group_id`.
- Text-only messages (`12.50 boulangerie`, `35 courses`) are expenses too when they parse as an amount; otherwise ignore them.

## Sandbox (autonomous work)

`sandbox.ps1` runs Claude Code with `--dangerously-skip-permissions` in Docker, on a separate clone `..\shared_budget_sandbox`, branch `agent`. The container has no host credentials, can't push, and reaches the internet only through a squid allowlist (`.sandbox/squid/squid.conf`). The agent's extra rules are in `.sandbox/agent-rules.md`. The agent commits on `agent` only; review, merge and push to GitHub happen on the host:

```powershell
.\sandbox.ps1 review     # what the agent committed
.\sandbox.ps1 publish    # merge agent into master after a y/N prompt, push to GitHub
```
