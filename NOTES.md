# Notes

Decisions made while working, newest first.

## 2026-10-05: the late button presses were IPv6 handshakes stalling for 21 s

The slow-call warnings added on 2026-10-04 showed `getUpdates` taking 51.1 s instead of at most 30 s, every few minutes, plus an occasional read timeout. A 3-minute probe from the home PC (one TCP connect per second to each of Telegram's addresses) found the IPv6 handshake timing out after exactly 21 s in 6 of 51 tries, while IPv4 never took more than 0.05 s and DNS was instant. Python tries the IPv6 address first, and Windows waits 21 s before giving up on a stalled handshake, so every eighth connection or so lost 21 s. A button press that waited behind one got "query is too old".

Fix: `budget/net.py`, used by the Telegram and Gemini clients, opens connections IPv4 first and gives each address at most 5 s before trying the next. Proxies from the environment still apply. Nothing to change on the PC itself; the issue is between this home network and Telegram's IPv6 address.

## 2026-10-04: receipts are read by Gemini (free tier), through a queue

Owner's choice (option B of three): the Gemini API free tier, accepting that Google may use free-tier content to improve its products, over a local model on the home PC, which is often switched off. The bot will move to free 24/7 hosting next; recognition was built first and works in the current polling bot.

- **Queue in the database**: a photo or document sent through Telegram is stored with `recognition = 'pending'` (not text, not a transfer, not chat-export files, which live on someone's disk). Rows stored before this change were queued by the migration. `Recognizer.process_one` reads the oldest one; the polling loop calls `Bot.recognize_next` after each poll and polls every second while something is due.
- **Download again from Telegram** by `file_id` (`TelegramApi.download`, up to 20 MB). Nothing is written to disk: photos stay on Telegram's servers.
- **Gemini `generateContent`** with `responseJsonSchema` (`budget/gemini.py`), standard library only, key in the `x-goog-api-key` header so no error can show it. `models.generateContent` is still supported next to the newer Interactions API, and its response shape is documented, so it was preferred. Default model `gemini-3.5-flash-lite` (cheapest, largest free quota); `GEMINI_MODEL=gemini-3.8-flash` reads more accurately. The system prompt spells out French receipt wording: which line is the total, what is not an item, dates as DD/MM/YYYY.
- **Checking the answer** (`parse_receipt`): a total of 0 or less means unreadable; a date in the future or more than 400 days back is a misreading and the message date stays; currency must be a 3-letter code; card digits must be exactly 4. Items whose sum is off the total by more than 2 cents are kept, and the message says something was read inaccurately.
- **What people typed wins**: the amount is filled only when empty (if it differs, the message shows the receipt's total and how to take it); the description only when empty. The receipt's date replaces the message's day, keeping the time of day, as with dates typed in a text.
- **Failures**: quota (429 with `retryDelay`), overload, network and garbled answers are retried, pausing the whole queue with backoff from 30 s up to an hour; after 5 attempts, or at once for a lasting error (400, file too big), the receipt becomes `failed` and the card asks for the amount, as before.
- `python -m budget read-receipt photo.jpg [--model ...]` reads one local file and prints the answer, to try models on real receipts without touching the database.
- Line items go to a new `items` table (name, quantity, amount, negative for a discount), deleted with their expense.

## 2026-10-04: a late button press must not freeze the card

Live run: pressing "Категория" did nothing; the log showed `answerCallbackQuery: Bad Request: query is too old`. The handler answered the press first and edited the card second, so a refused answer raised and the menu never opened. `Bot.answer_callback` now logs a refused answer as a warning and carries on. Why the press arrived late is not known: a request to api.telegram.org from the same machine took 0.2 s, and only one bot process was running. `TelegramApi.call` now warns about any call more than 3 s slower than expected (`getUpdates` included, beyond its long-poll timeout), so the next delay shows where the time goes.

## 2026-10-04: dates in the text, reports over several months, amounts after a receipt

Found in the first live run: the owner sent a receipt photo, the bot asked for the amount, and he typed `15.62` as a new message instead of a Telegram reply to the card. It became a second expense and the receipt stayed without an amount.

- **Bare amount after a card that asks for one** (`Bot.fill_awaiting`): the last card shown without an amount waits per chat for 30 minutes (`awaiting_for`); the next plain text that is only an amount (a date may follow) fills that expense instead of becoming a new one. Text with a description (`12 café`), forwards and replies keep their old meaning. The wait lives in memory, so a restarted bot forgets it; opening a card with the button again re-arms it. Known limit: in a future group chat the wait is per chat, not per person.
- **Date at the end of a text** (`text_entry.parse_text_expense(text, sent)`): `dd.mm`, `dd/mm`, either with a year (`01.10.2025`, `01/10/25`), or `вчера` / `позавчера` / `hier` / `avant-hier`. Read only when what comes before it is an expense on its own, so a bare `12.10` stays 12,10 €; an impossible date (`31.02`) stays part of the description. Without a year the date is never in the future: `28.12` sent on 3 January means last December. Works for texts, captions, forwards and chat exports (it applies in `ingest.to_expense`).
- **The date replaces the day and keeps the message's time of day** (`ingest.on_day`). Two separate `5 café 01.10` messages therefore stay two expenses in the author+date+amount dedup, while the same message forwarded twice still matches itself.
- **Replies to a card**: an amount, an amount and a date (`23,90 01.10`), or only a date that can't be an amount (`01/10`, `01.10.2026`, `вчера`); `01.10` alone still means 1,10 €.
- **`/report 2026-08 2026-10`** (also `2026-08..2026-10`, either order): one table for the period plus a "По месяцам" table with every month, empty ones included. No "where to save" block for a range, since it compares one month with the month before. `build_report(..., last_month=)`; `month_balance` then covers the whole period.
- **Left-out expenses**: `/balance` and `/report` name them (`нет суммы: #1`) and add an open button per expense instead of the old "Не учтено — без суммы: 1".

## 2026-10-04: the bot shows who spent what, never who owes whom

Owner's call after the first live run: no "Долг: X → Y" lines and no debt wording anywhere in the bot.

- `/report` and `/balance` show a monospace table (`texts.spending_table`): a row per category, a column per member with what that member actually **paid** (`CategoryLine.paid_by`), then `Итого` and its `общие` / `личные` split. The old per-category numbers were 50/50 shares, so a 15,62 € receipt Artem paid read "Artem 7,81 · Ksenia 7,81"; `spent_by` (shares) is kept for the CSV export.
- `/balance` is now the current month's table, not an all-time debt balance. "Current month" comes from `Bot.today` (local date in `BUDGET_TZ`), which tests fix.
- The split rule, shares and debts still exist in `balance.py`, the CLI report and the CSV export; the bot just doesn't show them. The "(деление 50/50)" header is gone with them.
- Reimbursements are called "перевод" in the bot (card, buttons, help, report section "Переводы друг другу"); the logic is unchanged: a transfer between the two is not spending. The text triggers (`вернул 32`, `remboursé 32`) stay.
- The table has no "total" column so it stays about 32 characters wide and fits a phone screen without wrapping; the month's grand total is in the "Учтено трат" line above it.

## 2026-10-02: "where to save" block in the monthly report

`budget/savings.py`, shown in `python -m budget report` ("Where to save") and in the bot's `/report` ("Где можно сэкономить"). Uses only counted expenses (amount known, not a reimbursement, report currency), shared and personal together.

- **Recurring payments**: same seller and exactly the same amount in each of the last 3 months, ending with the report month. Shows the monthly and yearly cost. Seller = description normalised like categories (`Netflix` = `netflix`). A price change (Spotify 10.99 → 11.99) breaks the streak until three months at the new price; that's on purpose for "the same amount", but see the question below.
- **Frequent small spending**: at least 8 expenses of up to 10 € in one category in the month, grouped by category (a bakery or café habit shows up even when the shop changes).
- **Delivery and eating out**: total of the `delivery` and `eating out` categories, their share of the month's counted spending, and the previous month's share for comparison.
- Nothing found → "nothing stands out" / "Ничего не бросается в глаза."

### Open questions for the owner (2026-10-02)

Defaults chosen so the work could go on; each is a constant in `budget/savings.py`:

1. Recurring: is 3 months in a row right, or should 2 be enough to flag a subscription? Should a small price change (say up to 10 %) still count as the same payment?
2. Small spending: is "up to 10 €, at least 8 times a month, per category" the right threshold?
3. Delivery and eating out: compare with the previous month only, or with an average over several months? Is a target share wanted (e.g. warn above 20 %)?
4. Should the savings block look at shared expenses only, or (as now) shared and personal together?

## 2026-10-02: CSV export

`python -m budget export --month 2026-10 [--out file.csv|-] [--plain] [--split 60/40]` (`budget/export.py`). Without `--month`, everything.

- **Format**: default is for Excel in France: `;` separator, decimal comma, UTF-8 with BOM (otherwise Excel shows accents and Cyrillic as mojibake), CRLF. `--plain`: `,` and decimal point, for Power BI / pandas. Every row also has `amount_cents`, an integer that no locale can misread.
- **Columns**: id, local date, time and month (Nice time, same month boundaries as the report), type (`expense`/`reimbursement`), amount, amount_cents, currency, payer key and display name, paid_to, shared (yes/no), category (English key, guessed if not set), description, `share_<member>` per member under the split rule (personal expenses: all on the payer), author, source, kind, payer_confirmed.
- Expenses without an amount are exported with empty amount and shares, so they can be counted or filtered; reimbursements have no category, shared flag or shares.
- Default output path is next to the database (`data/expenses-2026-10.csv`), which is gitignored; `expenses-*.csv` is gitignored too, since an export holds real amounts.
- Cells starting with `= + - @` get a leading `'` so a description can't run as a spreadsheet formula. A negative amount never occurs (amounts are positive), so the `-` rule only touches text.

## 2026-10-02: more category rules

- `budget/categories.py` now knows the common French chains (Carrefour, Monoprix, Franprix, Lidl, Aldi, Picard, Intermarché, Leclerc, Auchan, Super U, Biocoop, Grand Frais, Casino...), transport (SNCF, TER, Ouigo, Lignes d'Azur, Zou, TotalEnergies, Vinci, Indigo), home (IKEA, Leroy Merlin, EDF...), telecom/streaming, and Russian words, since descriptions may be typed in Russian.
- New categories: `delivery` (Uber Eats, Deliveroo, Just Eat, `livraison`, `доставка`; split from eating out for the savings block), `electronics` (Fnac, Darty, Boulanger), `beauty`, `pets`. Russian labels in `texts.py`.
- Matching ignores case and accents and treats punctuation as spaces (`Lignes d’Azur` = `lignes d azur`). Keywords match a word prefix, or the whole word with a leading `=` for short or ambiguous ones (`=bar` ≠ `barbier`, `=boulanger` ≠ `boulangerie`, `=uber` ≠ `uber eats`). Phrases are tried before single words; when words disagree, the category listed first wins (delivery first, so `Deliveroo pizza` is delivery).
- `livraison` alone counts as delivery even if it was a parcel; correct it on the card.
- Changed outcome for existing data: `uber eats` / `livraison` used to be "eating out" and are now "delivery".

## 2026-10-02: paybacks from Telegram

- A text (message, caption, or chat-export entry) is a payback when a payback word comes right before the amount (`remboursé 32`, `вернул долг 15`, `возврат долга: 20`, `remb. 10`, `отдал 5`) or right after it (`32 remboursé`, `32 euros remboursés`). Words: `rembours*`, `remb`, `вернул/вернула/вернули`, `верну`, `возврат*`, `отдал*`, optionally followed by `долг`/`la dette`. Anything after the amount becomes the description.
- The author (or forwarder, as for expenses) is who paid back; the receiver is the other member. With more than two members `paid_to` stays empty (counted as "without a payer") until chosen on the card.
- Replying `remboursé 32` to a card both sets the amount and marks the entry a payback (useful for a transfer screenshot).
- The card button "Это возврат долга" already existed (previous commit) and stays the way to fix a misread.
- Known ambiguity: `вернул 32` could also mean returning goods to a shop. The card shows "Возврат долга" and "Это не возврат, а трата" flips it back.

## 2026-10-02: live Telegram bot

`python -m budget bot`: long polling, token from `TELEGRAM_BOT_TOKEN`. Modules: `budget/telegram_api.py` (client), `budget/bot.py` (logic + polling loop), `budget/texts.py` (every string the bot sends, Russian, HTML parse mode).

Decisions:
- **Library: none.** A ~60-line client on `urllib` calling the Bot API directly (`getUpdates`, `sendMessage`, `editMessageText`, `answerCallbackQuery`, `deleteWebhook`, `setMyCommands`). Considered python-telegram-bot (LGPL, async, big) and aiogram (MIT, async): both free, but for seven methods they add a dependency with frequent breaking releases, and offline tests need their internals mocked. Here tests swap the client for a fake with the same `call(method, **params)`. Errors never contain the URL (it holds the token); `retry_after` from 429 is respected; network errors back off 1→60 s. Switching to a library later only touches `telegram_api.py` and `run()`.
- **Who is answered**: only messages and button presses from the configured member ids; everyone else is ignored silently (button presses get a "only for members" toast, since Telegram needs an answer to stop the spinner).
- **Batches**: every message is stored on arrival; the reply waits until the same sender in the same chat has been quiet for 2 s (polling switches from 30 s to 1 s while a batch waits). One message → its card (or "already saved" + the existing card, or a hint for a text without an amount). Several → one summary listing added / already saved / skipped, with an "open" button per expense (up to 30 listed); pressing it sends that expense's card. So "a card per expense" holds, but on demand, as the user asked for one answer per batch.
- **Cards**: amount (or "без суммы"), date in Nice time, payer (marked "по умолчанию" until confirmed), shared/personal, category (marked "по описанию" when guessed), description, source. Buttons: payer menu, shared⇄personal, category menu (Russian labels for the keys in `categories.py`; stored value stays the English key), "this is a reimbursement" (to the other member; with more members a menu), delete with confirmation. Reimbursement cards hide shared and category. Changing the payer of a reimbursement to its receiver swaps the receiver.
- **Amount by reply**: replying to a card with `23,90` or `23,90 pharmacie` saves it via `set_amount` (and the description if the expense had none), edits the card and confirms. A reply also corrects an existing amount. New table `cards (chat_id, message_id, expense_id)` maps bot messages to expenses; rows go when the expense is deleted (FK cascade, `PRAGMA foreign_keys = ON`).
- **Delete is a hard delete**; forwarding the same receipt again afterwards adds it again (dedup has nothing to match).
- `/balance`: everything ever, with `BUDGET_SPLIT`. `/report [YYYY-MM]`: default current month in Nice. Texts are gender-neutral ("Долг: A → B", "оплачено") since the bot doesn't know the members' genders.
- Shutdown (Ctrl+C) answers waiting batches before closing the database.
- Not checked live: no token in the sandbox. First live run on the host: `python -m budget bot`, then forward a few messages.

## 2026-10-02: reimbursements (paying back a debt)

Modelled as in Spliit: a reimbursement is a row in `expenses` with `is_reimbursement = 1`; `payer` is who gives the money, new column `paid_to` is who gets it. Old databases get both columns on open.

Decisions:
- **Effect**: only the nets move (`net = paid_shared - share + sent - received`). Not spending: excluded from totals, `spent`, categories and the expense count; independent of the split rule.
- **Recording**: `python -m budget reimburse --from sam --to alex --amount 32.50 [--date YYYY-MM-DD] [--note ...]` (`Store.add_reimbursement`), stored with `source = 'manual'`. A bare `--date` means 12:00 local time, safely inside that day and month; no date means now. Running it twice records two transfers on purpose: no dedup, two equal transfers on the same day are possible.
- `Store.mark_reimbursement(id, paid_to)` turns a stored entry (say a forwarded bank-transfer screenshot) into a reimbursement, or back with `None`; for the bot's future "this was a payback" button.
- **Report**: a "Reimbursements" list for the month, and "paid back" / "got back" columns in the member table when the month has any. The month's balance includes that month's reimbursements, so a payback that also covered earlier months can make the month's line flip (e.g. "alex owes sam 5 €"); the running balance ("everything up to the end of the month") is the one to settle.
- Skipped like expenses: a reimbursement whose receiver isn't a member counts as "without a payer"; one in another currency as "other currency".
- Still to do in the bot: recognising a payback from Telegram (a text like `remboursé 32` or a transfer screenshot). Not done here.

## 2026-10-02: balance and monthly report

Modules: `budget/balance.py` (split rule, balance, settlement), `budget/categories.py`, `budget/report.py`; command `python -m budget report --month 2026-10 [--split 60/40]`.

Decisions:
- **Split rule** is a parameter (`SplitRule`), never stored: weights per member key. `--split 60/40` (or `BUDGET_SPLIT` in `.env`) gives weights in member order (MEMBER_1, MEMBER_2); default even. Shares are whole cents that add up to the amount exactly (largest remainder; a tie for the leftover cent goes to the first member).
- **Balance**: per member `paid_shared`, `paid_personal`, `share` (their part of every shared expense), `net = paid_shared - share` (positive = is owed), `spent = share + personal`. Personal expenses appear in totals but never create debt. Debts come from a greedy settlement of the nets (exact for two people, works for more).
- **Not counted, shown as counters**: no amount (receipt not recognised yet), payer missing or not a configured member key, currency other than the report's (`--currency`, default EUR). No conversion between currencies.
- **Month** is a calendar month in local time (`BUDGET_TZ`, default Europe/Paris), so 23:30 UTC on 31 Oct counts in November. The report shows the month's balance and the running balance of everything up to the end of the month. Reimbursements: see the entry above.
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
