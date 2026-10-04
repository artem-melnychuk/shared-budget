"""The Telegram bot: long polling, expense cards with buttons, /balance, /report.

Messages are stored as soon as they arrive; replies are held back per chat
and sender until no new message has come for `debounce` seconds, so a batch
of forwarded messages gets one summary instead of one answer each.
"""

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from budget import texts
from budget.balance import SplitRule
from budget.categories import category_of
from budget.ingest import ingest_update, on_day
from budget.members import Members
from budget.report import DEFAULT_TZ, build_report, parse_period
from budget.storage import Expense, Store, iso
from budget.telegram_api import TelegramError
from budget.text_entry import parse_date_only, parse_text_expense

log = logging.getLogger(__name__)

COMMANDS = [
    {"command": "balance", "description": "Кто сколько потратил в этом месяце"},
    {"command": "report", "description": "Отчёт за месяц: /report 2026-10"},
    {"command": "help", "description": "Что умеет бот"},
]


@dataclass
class Batch:
    chat_id: int
    first_message_id: int
    last_seen: float
    received: int = 0
    added: list[int] = field(default_factory=list)
    duplicates: list[int] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)


class Bot:
    def __init__(self, store: Store, members: Members, api, rule: SplitRule,
                 tz_name: str = DEFAULT_TZ, clock=time.monotonic, debounce: float = 2.0,
                 list_limit: int = 30, today=None, awaiting_for: float = 1800, recognizer=None):
        self.store = store
        self.recognizer = recognizer       # budget.recognize.Recognizer, or None: amounts typed by hand
        self.members = members
        self.api = api
        self.rule = rule
        self.tz_name = tz_name
        self.clock = clock
        # Local date in the budget's time zone; tests pass a fixed one.
        self.today = today or (lambda: datetime.now(ZoneInfo(self.tz_name)).date())
        self.debounce = debounce
        self.list_limit = list_limit
        self.pending: dict[tuple[int, int], Batch] = {}
        # chat id -> (expense id, clock) of the last card shown without an amount: a bare
        # amount sent next in that chat fills it in instead of becoming a new expense.
        self.awaiting: dict[int, tuple[int, float]] = {}
        self.awaiting_for = awaiting_for

    # --- sending -------------------------------------------------------------

    def send(self, chat_id: int, text: str, keyboard=None, reply_to: int | None = None) -> dict:
        params = dict(chat_id=chat_id, text=text, parse_mode="HTML",
                      link_preview_options={"is_disabled": True})
        if keyboard is not None:
            params["reply_markup"] = {"inline_keyboard": keyboard}
        if reply_to is not None:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return self.api.call("sendMessage", **params)

    def edit(self, chat_id: int, message_id: int, text: str, keyboard=None):
        try:
            self.api.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                          parse_mode="HTML", link_preview_options={"is_disabled": True},
                          reply_markup={"inline_keyboard": keyboard or []})
        except TelegramError as e:
            if not e.not_modified:
                raise

    def card_text(self, e: Expense, duplicate: bool = False) -> str:
        items = self.store.items(e.id) if e.recognition == "done" else None
        return texts.card(e, self.members, self.tz_name, duplicate, items=items,
                          reading=self.recognizer is not None)

    def send_card(self, chat_id: int, e: Expense, reply_to: int | None = None, duplicate: bool = False):
        sent = self.send(chat_id, self.card_text(e, duplicate), self.card_keyboard(e), reply_to)
        self.store.add_card(chat_id, sent["message_id"], e.id)
        if e.amount_cents is None and not e.is_reimbursement:
            self.awaiting[chat_id] = (e.id, self.clock())

    def open_keyboard(self, expenses: list[Expense]) -> list[list[dict]] | None:
        """Two "#id · amount" buttons per row; each sends that expense's card."""
        buttons = [_button(texts.BTN_OPEN.format(id=e.id, amount=texts.money(e.amount_cents, e.currency)),
                           f"o:{e.id}") for e in expenses[:self.list_limit]]
        return [buttons[i:i + 2] for i in range(0, len(buttons), 2)] or None

    # --- keyboards -----------------------------------------------------------

    def card_keyboard(self, e: Expense) -> list[list[dict]]:
        b = _button
        rows = [[b(texts.BTN_PAYER.format(name=self.members.display(e.payer)), f"p:{e.id}")]]
        if e.is_reimbursement:
            rows.append([b(texts.BTN_NOT_REIMBURSEMENT, f"r:{e.id}")])
        else:
            rows[0].append(b(texts.BTN_SHARED if e.is_shared else texts.BTN_PERSONAL, f"s:{e.id}"))
            rows.append([b(texts.BTN_CATEGORY, f"c:{e.id}"), b(texts.BTN_REIMBURSEMENT, f"r:{e.id}")])
        rows.append([b(texts.BTN_DELETE, f"d:{e.id}")])
        return rows

    def _member_keyboard(self, e: Expense, action: str, current: str | None, exclude: str | None = None):
        rows = [[_button(texts.BTN_CHOSEN.format(label=m.display) if m.key == current else m.display,
                         f"{action}:{e.id}:{i}")]
                for i, m in enumerate(self.members.members) if m.key != exclude]
        return rows + [[_button(texts.BTN_BACK, f"b:{e.id}")]]

    def _category_keyboard(self, e: Expense):
        current = category_of(e) if e.category else None
        buttons = [_button(texts.BTN_CHOSEN.format(label=texts.category_label(c)) if c == current
                           else texts.category_label(c), f"C:{e.id}:{i}")
                   for i, c in enumerate(texts.CATEGORIES)]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        return rows + [[_button(texts.BTN_BACK, f"b:{e.id}")]]

    # --- updates -------------------------------------------------------------

    def handle_update(self, update: dict):
        if "callback_query" in update:
            self.handle_callback(update["callback_query"])
        elif "message" in update:
            self.handle_message(update)

    def handle_message(self, update: dict):
        message = update["message"]
        sender = self.members.by_user_id((message.get("from") or {}).get("id"))
        if sender is None:
            return  # only members are answered
        chat_id = message["chat"]["id"]
        text = message.get("text")
        reply = message.get("reply_to_message")
        if reply and text and "forward_origin" not in message:
            card_expense = self.store.card_expense(chat_id, reply["message_id"])
            if card_expense is not None:
                self.amount_reply(chat_id, message["message_id"], reply["message_id"], card_expense, text)
                return
        if text and text.startswith("/") and "forward_origin" not in message:
            self.command(chat_id, text)
            return
        if text and "forward_origin" not in message and self.fill_awaiting(chat_id, message["message_id"], text):
            return

        result = ingest_update(self.store, self.members, update, tz_name=self.tz_name)
        key = (chat_id, message["from"]["id"])
        batch = self.pending.get(key)
        if batch is None:
            batch = self.pending[key] = Batch(chat_id, message["message_id"], self.clock())
        batch.last_seen = self.clock()
        batch.received += 1
        if result.status == "added":
            batch.added.append(result.expense_id)
        elif result.status == "duplicate":
            if result.expense_id not in batch.duplicates and result.expense_id not in batch.added:
                batch.duplicates.append(result.expense_id)
        else:
            batch.skipped[result.reason] += 1

    def fill_awaiting(self, chat_id: int, message_id: int, text: str) -> bool:
        """A bare amount (optionally with a date) right after a card that asked for one.

        Returns True when it went into that expense. Anything with a description
        (`12 café`) is a new expense, as before.
        """
        waiting = self.awaiting.get(chat_id)
        if waiting is None:
            return False
        expense_id, since = waiting
        e = self.store.get(expense_id)
        if self.clock() - since > self.awaiting_for or e is None or e.amount_cents is not None:
            del self.awaiting[chat_id]
            return False
        parsed = parse_text_expense(text, self.today())
        if parsed is None or parsed.description or parsed.is_reimbursement:
            return False
        self.amount_reply(chat_id, message_id, self.store.last_card(chat_id, e.id), e, text)
        return True

    def amount_reply(self, chat_id: int, message_id: int, card_id: int | None, e: Expense, text: str):
        """A reply to a card: an amount, an amount and a date, or only a date."""
        day = parse_date_only(text, self.today())
        parsed = None if day else parse_text_expense(text, self.today())
        if day is None and parsed is None:
            self.send(chat_id, texts.NOT_AN_AMOUNT, reply_to=message_id)
            return
        if parsed is not None:
            self.store.set_amount(e.id, parsed.amount_cents, e.currency)
            if parsed.description and not e.description:
                self.store.set_description(e.id, parsed.description)
            if parsed.is_reimbursement and not e.is_reimbursement:
                self.store.mark_reimbursement(e.id, self._other(e.payer))
            day = parsed.day
        if day is not None:
            when = on_day(datetime.fromisoformat(e.original_date), day, self.tz_name)
            self.store.set_date(e.id, iso(when))
        if self.awaiting.get(chat_id, (None,))[0] == e.id:
            del self.awaiting[chat_id]
        e = self.store.get(e.id)
        if card_id is not None:
            self.edit(chat_id, card_id, self.card_text(e), self.card_keyboard(e))
        amount = texts.money(e.amount_cents, e.currency)
        date_text = texts.local_date(e.original_date, self.tz_name)
        if parsed is None:
            confirmation = texts.DATE_SAVED.format(id=e.id, date=date_text)
        elif day is None:
            confirmation = texts.AMOUNT_SAVED.format(id=e.id, amount=amount)
        else:
            confirmation = texts.AMOUNT_AND_DATE_SAVED.format(id=e.id, amount=amount, date=date_text)
        self.send(chat_id, confirmation, reply_to=message_id)

    def command(self, chat_id: int, text: str):
        name, *args = text.split()
        name = name.split("@", 1)[0].lower()
        if name == "/balance":
            report = build_report(self.store, self.today().replace(day=1), self.rule, tz_name=self.tz_name)
            self.send(chat_id, texts.balance_message(report, self.members),
                      self.open_keyboard(texts.not_counted_expenses(report.month_balance)))
        elif name == "/report":
            try:
                first, last = parse_period(args) if args else (self.today().replace(day=1),) * 2
            except ValueError:
                self.send(chat_id, texts.BAD_MONTH)
                return
            report = build_report(self.store, first, self.rule, tz_name=self.tz_name, last_month=last)
            self.send(chat_id, texts.report_message(report, self.members),
                      self.open_keyboard(texts.not_counted_expenses(report.month_balance)))
        else:
            self.send(chat_id, texts.HELP)

    # --- batches -------------------------------------------------------------

    def has_pending(self) -> bool:
        return bool(self.pending)

    def has_work(self) -> bool:
        """Something to do soon: a batch to answer or a receipt to read."""
        return self.has_pending() or (self.recognizer is not None and self.recognizer.due())

    # --- receipts ------------------------------------------------------------

    def recognize_next(self):
        """Read one queued receipt, then update its card and say what was read."""
        if self.recognizer is None or not self.recognizer.due():
            return
        outcome = self.recognizer.process_one()
        if outcome is None or outcome.status == "retry":
            return
        e = outcome.expense
        if e.chat_id is None:
            return
        card_id = self.store.last_card(e.chat_id, e.id)
        if card_id is not None:
            self.edit(e.chat_id, card_id, self.card_text(e), self.card_keyboard(e))
        if outcome.status == "done":
            text = texts.recognized(outcome, self.store.items(e.id), self.members, self.tz_name)
            if self.awaiting.get(e.chat_id, (None,))[0] == e.id and e.amount_cents is not None:
                del self.awaiting[e.chat_id]
        else:
            text = texts.recognition_failed(e)
            if e.amount_cents is None:
                self.awaiting[e.chat_id] = (e.id, self.clock())
        keyboard = None if card_id is not None else self.open_keyboard([e])
        self.send(e.chat_id, text, keyboard, reply_to=card_id)

    def flush_due(self):
        now = self.clock()
        for key, batch in list(self.pending.items()):
            if now - batch.last_seen >= self.debounce:
                del self.pending[key]
                self.answer_batch(batch)

    def flush_all(self):
        batches, self.pending = list(self.pending.values()), {}
        for batch in batches:
            self.answer_batch(batch)

    def answer_batch(self, batch: Batch):
        added = [e for e in map(self.store.get, batch.added) if e]
        duplicates = [e for e in map(self.store.get, batch.duplicates) if e]
        if batch.received == 1:
            if added:
                self.send_card(batch.chat_id, added[0], reply_to=batch.first_message_id)
            elif duplicates:
                self.send_card(batch.chat_id, duplicates[0], reply_to=batch.first_message_id, duplicate=True)
            else:
                self.send(batch.chat_id, texts.NOT_AN_EXPENSE, reply_to=batch.first_message_id)
            return
        text = texts.batch_summary(batch.received, added, duplicates, dict(batch.skipped),
                                   self.members, self.tz_name, self.list_limit)
        listed = (added[:self.list_limit] + duplicates[:self.list_limit])
        self.send(batch.chat_id, text, self.open_keyboard(listed), reply_to=batch.first_message_id)

    # --- buttons -------------------------------------------------------------

    def answer_callback(self, query_id: str, text: str | None = None):
        """Stop the button's spinner (and show a toast). Never fatal: Telegram refuses an
        answer that comes too late, and the edit that follows matters more than the toast."""
        try:
            self.api.call("answerCallbackQuery", callback_query_id=query_id, text=text)
        except TelegramError as e:
            log.warning("could not answer a button press: %s", e)

    def handle_callback(self, query: dict):
        query_id = query["id"]
        if self.members.by_user_id(query["from"]["id"]) is None:
            self.answer_callback(query_id, texts.TOAST_NOT_ALLOWED)
            return
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        message_id = message.get("message_id")
        try:
            action, expense_id, *rest = (query.get("data") or "").split(":")
            e = self.store.get(int(expense_id))
            arg = int(rest[0]) if rest else None
        except ValueError:
            e = None
        if e is None or chat_id is None:
            self.answer_callback(query_id, texts.TOAST_NOT_FOUND)
            return

        toast = None
        keyboard = None   # None: show the card with its normal buttons
        extra = ""
        if action == "o":
            self.answer_callback(query_id)
            self.send_card(chat_id, e, reply_to=message_id)
            return
        if action == "d":
            extra, keyboard = texts.DELETE_CONFIRM, [[_button(texts.BTN_DELETE_YES, f"D:{e.id}"),
                                                       _button(texts.BTN_BACK, f"b:{e.id}")]]
        elif action == "D":
            self.store.delete(e.id)
            self.answer_callback(query_id, texts.TOAST_DELETED)
            self.edit(chat_id, message_id, texts.deleted(e.id))
            return
        elif action == "p":
            extra, keyboard = texts.CHOOSE_PAYER, self._member_keyboard(e, "P", e.payer)
        elif action == "P" and self._member(arg):
            payer = self._member(arg).key
            self.store.set_payer(e.id, payer)
            if e.is_reimbursement and e.paid_to == payer:
                self.store.set_paid_to(e.id, self._other(payer))
            toast = texts.TOAST_SAVED
        elif action == "s" and not e.is_reimbursement:
            self.store.set_shared(e.id, not e.is_shared)
            toast = texts.TOAST_SAVED
        elif action == "c" and not e.is_reimbursement:
            extra, keyboard = texts.CHOOSE_CATEGORY, self._category_keyboard(e)
        elif action == "C" and arg is not None and 0 <= arg < len(texts.CATEGORIES):
            self.store.set_category(e.id, texts.CATEGORIES[arg])
            toast = texts.TOAST_SAVED
        elif action == "r":
            if e.is_reimbursement:
                self.store.mark_reimbursement(e.id, None)
                toast = texts.TOAST_SAVED
            else:
                others = [m for m in self.members.members if m.key != e.payer]
                if len(others) == 1:
                    self.store.mark_reimbursement(e.id, others[0].key)
                    toast = texts.TOAST_SAVED
                else:
                    extra, keyboard = texts.CHOOSE_RECEIVER, self._member_keyboard(e, "R", None, e.payer)
        elif action == "R" and self._member(arg):
            self.store.mark_reimbursement(e.id, self._member(arg).key)
            toast = texts.TOAST_SAVED
        # "b" (back) and anything unknown just redraw the card.

        self.answer_callback(query_id, toast)
        e = self.store.get(e.id)
        self.edit(chat_id, message_id, self.card_text(e) + extra,
                  keyboard if keyboard is not None else self.card_keyboard(e))
        self.store.add_card(chat_id, message_id, e.id)

    def _member(self, index: int | None):
        if index is None or not 0 <= index < len(self.members.members):
            return None
        return self.members.members[index]

    def _other(self, key: str) -> str | None:
        return next((m.key for m in self.members.members if m.key != key), None)


def _button(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def run(bot: Bot, api, sleep=time.sleep, should_stop=lambda: False, poll_timeout: int = 30):
    """Long polling until `should_stop()` or Ctrl+C."""
    api.call("deleteWebhook")
    api.call("setMyCommands", commands=COMMANDS)
    offset = None
    backoff = 1
    while not should_stop():
        try:
            updates = api.call("getUpdates", offset=offset, allowed_updates=["message", "callback_query"],
                               timeout=1 if bot.has_work() else poll_timeout)
            backoff = 1
        except TelegramError as e:
            delay = e.retry_after or backoff
            log.warning("getUpdates failed (%s); retrying in %ss", e, delay)
            sleep(delay)
            backoff = min(backoff * 2, 60)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            try:
                bot.handle_update(update)
            except Exception:
                log.exception("update %s failed", update.get("update_id"))
        try:
            bot.flush_due()
        except Exception:
            log.exception("answering a batch failed")
        try:
            bot.recognize_next()
        except Exception:
            log.exception("reading a receipt failed")
