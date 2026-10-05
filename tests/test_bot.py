import html
import io
import json
import os
import re
import unittest
import urllib.error
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from unittest import mock

from budget import texts
from budget.__main__ import main
from budget.balance import SplitRule
from budget.bot import Bot, run
from budget.gemini import GeminiError
from budget.recognize import Recognizer
from budget.storage import Store
from budget.telegram_api import TelegramApi, TelegramError
from tests.fakes import (ALEX, ALEX_ID, ENV, SAM, STRANGER_ID, from_hidden,
                         from_user, members, photo_sizes, update, user)

KEYS = ["alex", "sam"]


def table_rows(text, n=0):
    """Cells of the n-th monospace table in a bot message, split on runs of 2+ spaces."""
    pre = re.findall(r"<pre>(.*?)</pre>", text, re.S)[n]
    return [re.split(r"\s{2,}", line.strip()) for line in html.unescape(pre).splitlines()]


def epoch(*args):
    """Unix time of a UTC moment, for message dates."""
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


class FakeApi:
    """Records calls; sendMessage returns a message with a fresh id."""

    def __init__(self, updates=None, errors=None):
        self.calls = []
        self.next_id = 9000
        self.updates = list(updates or [])
        self.errors = dict(errors or {})

    def call(self, method, **params):
        self.calls.append((method, params))
        if method in self.errors:
            raise self.errors.pop(method)
        if method == "sendMessage":
            self.next_id += 1
            return {"message_id": self.next_id, "chat": {"id": params["chat_id"]}, "text": params["text"]}
        if method == "getUpdates":
            return self.updates.pop(0) if self.updates else []
        return True

    def sent(self, method="sendMessage"):
        return [p for m, p in self.calls if m == method]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def callback(data, message_id, sender=ALEX, query_id="q1"):
    return {"update_id": 777, "callback_query": {
        "id": query_id, "from": sender, "data": data, "chat_instance": "ci",
        "message": {"message_id": message_id, "chat": {"id": sender["id"], "type": "private"}, "date": 0},
    }}


def buttons(params):
    return [b for row in params["reply_markup"]["inline_keyboard"] for b in row]


class BotTestCase(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.api = FakeApi()
        self.clock = Clock()
        self.bot = Bot(self.store, members(), self.api, SplitRule.even(KEYS), clock=self.clock, debounce=2)

    def tearDown(self):
        self.store.close()

    def feed(self, *updates, flush=True):
        for u in updates:
            self.bot.handle_update(u)
        if flush:
            self.clock.now += 5
            self.bot.flush_due()

    def card_for(self, upd):
        """Feed one message and return (expense, card message id)."""
        self.feed(upd)
        return self.store.all()[-1], self.api.next_id


class SingleMessageTest(BotTestCase):
    def test_photo_gets_a_card_after_the_pause(self):
        self.bot.handle_update(update(10, origin=from_user(SAM), photo=photo_sizes("rcpt-A")))
        self.clock.now += 1
        self.bot.flush_due()
        self.assertEqual(self.api.sent(), [])
        self.clock.now += 2
        self.bot.flush_due()
        [card] = self.api.sent()
        self.assertEqual(card["reply_parameters"]["message_id"], 10)
        self.assertEqual(card["parse_mode"], "HTML")
        self.assertIn("без суммы", card["text"])
        self.assertIn("Пришлите сумму следующим сообщением", card["text"])
        self.assertIn("Sam Example", card["text"])
        self.assertIn("14.03.2026", card["text"])
        data = [b["callback_data"] for b in buttons(card)]
        e = self.store.all()[0]
        self.assertEqual(data, [f"p:{e.id}", f"s:{e.id}", f"c:{e.id}", f"r:{e.id}", f"d:{e.id}"])
        self.assertEqual(self.store.card_expense(ALEX_ID, self.api.next_id).id, e.id)
        self.assertFalse(self.bot.has_pending())

    def test_text_expense_card(self):
        self.feed(update(11, text="12.50 boulangerie"))
        text = self.api.sent()[0]["text"]
        self.assertIn("12,50 €", text)
        self.assertIn("Булочная (по описанию)", text)
        self.assertIn("общая", text)

    def test_chat_text_gets_a_hint(self):
        self.feed(update(12, text="on mange où ?"))
        self.assertEqual(self.api.sent()[0]["text"], texts.NOT_AN_EXPENSE)
        self.assertEqual(self.store.all(), [])

    def test_duplicate_shows_the_existing_card(self):
        self.feed(update(13, photo=photo_sizes("rcpt-B")))
        self.feed(update(14, sender=SAM, photo=photo_sizes("rcpt-B")))
        card = self.api.sent()[-1]
        self.assertTrue(card["text"].startswith(texts.ALREADY_SAVED))
        self.assertEqual(len(self.store.all()), 1)

    def test_strangers_are_ignored(self):
        self.feed(update(15, sender=user(STRANGER_ID, "Stranger"), text="10 hack"),
                  update(16, sender=user(STRANGER_ID, "Stranger"), text="/balance"))
        self.assertEqual(self.api.calls, [])
        self.assertEqual(self.store.all(), [])


class BatchTest(BotTestCase):
    def test_forwarded_batch_gets_one_summary(self):
        self.feed(update(10, photo=photo_sizes("rcpt-A")))  # already known
        self.api.calls.clear()
        self.feed(
            update(20, origin=from_user(SAM), photo=photo_sizes("rcpt-A")),
            update(21, origin=from_user(SAM), text="12.50 boulangerie"),
            update(22, origin=from_hidden("Sammy"), photo=photo_sizes("rcpt-C"), media_group_id="al-1"),
            update(23, origin=from_hidden("Sammy"), photo=photo_sizes("rcpt-D"), media_group_id="al-1"),
            update(24, origin=from_user(SAM), text="tu rentres quand ?"),
        )
        [summary] = self.api.sent()
        self.assertEqual(summary["reply_parameters"]["message_id"], 20)
        text = summary["text"]
        self.assertIn("Получено сообщений: 5", text)
        self.assertIn("Добавлено: 3", text)
        self.assertIn("Уже были записаны: 1", text)
        self.assertIn("Пропущено: 1 (текст без суммы: 1)", text)
        self.assertIn("Без суммы: 2", text)
        self.assertEqual(len(buttons(summary)), 4)
        self.assertTrue(all(b["callback_data"].startswith("o:") for b in buttons(summary)))
        self.assertEqual(len(self.store.media_group("al-1")), 2)

    def test_messages_keep_the_batch_open(self):
        for i in range(3):
            self.bot.handle_update(update(30 + i, text=f"{i + 1} café"))
            self.clock.now += 1.5
            self.bot.flush_due()
        self.assertEqual(self.api.sent(), [])
        self.clock.now += 2
        self.bot.flush_due()
        self.assertEqual(len(self.api.sent()), 1)

    def test_each_sender_has_own_batch(self):
        self.feed(update(40, sender=ALEX, text="5 café"), update(41, sender=SAM, text="6 café"))
        self.assertEqual(len(self.api.sent()), 2)  # two single-message cards

    def test_open_button_sends_the_card(self):
        self.feed(update(50, text="5 café"), update(51, text="7 pain"))
        summary_id = self.api.next_id
        e = self.store.all()[0]
        self.feed(callback(f"o:{e.id}", summary_id), flush=False)
        card = self.api.sent()[-1]
        self.assertIn(f"Трата #{e.id}", card["text"])
        self.assertEqual(self.store.card_expense(ALEX_ID, self.api.next_id).id, e.id)

    def test_flush_all(self):
        self.bot.handle_update(update(60, text="5 café"))
        self.bot.flush_all()
        self.assertEqual(len(self.api.sent()), 1)


class AmountReplyTest(BotTestCase):
    def reply(self, text, card_id, message_id=70):
        return {"update_id": 1, "message": {
            "message_id": message_id, "from": ALEX, "chat": {"id": ALEX_ID, "type": "private"},
            "date": 1776161800, "text": text,
            "reply_to_message": {"message_id": card_id, "from": {"id": 1, "is_bot": True, "first_name": "bot"},
                                 "chat": {"id": ALEX_ID, "type": "private"}, "date": 1776161700, "text": "..."}}}

    def test_amount_by_reply(self):
        e, card_id = self.card_for(update(10, photo=photo_sizes("rcpt-A")))
        self.feed(self.reply("23,90 pharmacie", card_id), flush=False)
        e = self.store.get(e.id)
        self.assertEqual((e.amount_cents, e.description), (2390, "pharmacie"))
        [edit] = self.api.sent("editMessageText")
        self.assertEqual(edit["message_id"], card_id)
        self.assertIn("23,90 €", edit["text"])
        self.assertIn("Здоровье", edit["text"])
        self.assertIn("23,90 €", self.api.sent()[-1]["text"])
        self.assertFalse(self.bot.has_pending())
        self.assertEqual(len(self.store.all()), 1)

    def test_correcting_keeps_description(self):
        e, card_id = self.card_for(update(10, text="12.50 boulangerie"))
        self.feed(self.reply("13 pain", card_id), flush=False)
        e = self.store.get(e.id)
        self.assertEqual((e.amount_cents, e.description), (1300, "boulangerie"))

    def test_not_an_amount(self):
        e, card_id = self.card_for(update(10, photo=photo_sizes("rcpt-A")))
        self.feed(self.reply("merci", card_id), flush=False)
        self.assertEqual(self.api.sent()[-1]["text"], texts.NOT_AN_AMOUNT)
        self.assertIsNone(self.store.get(e.id).amount_cents)

    def test_reply_to_other_message_is_a_new_expense(self):
        self.card_for(update(10, photo=photo_sizes("rcpt-A")))
        self.feed(self.reply("8 café", 12345, message_id=71))
        self.assertEqual(len(self.store.all()), 2)

    def test_edit_not_modified_is_fine(self):
        e, card_id = self.card_for(update(10, text="12.50 boulangerie"))
        self.api.errors["editMessageText"] = TelegramError(
            "editMessageText: Bad Request: message is not modified", 400)
        self.feed(self.reply("12.50", card_id), flush=False)
        self.assertIn("12,50 €", self.api.sent()[-1]["text"])

    # The fixture photo was sent on 2026-04-14 at 10:15 UTC (12:15 in Nice).

    def test_amount_and_date_by_reply(self):
        self.bot.today = lambda: date(2026, 4, 14)
        e, card_id = self.card_for(update(10, photo=photo_sizes("rcpt-A")))
        self.feed(self.reply("23,90 01.04", card_id), flush=False)
        e = self.store.get(e.id)
        self.assertEqual((e.amount_cents, e.original_date), (2390, "2026-04-01T10:15:00+00:00"))
        self.assertIn("01.04.2026", self.api.sent("editMessageText")[-1]["text"])
        self.assertEqual(self.api.sent()[-1]["text"],
                         texts.AMOUNT_AND_DATE_SAVED.format(id=e.id, amount="23,90 €", date="01.04.2026"))

    def test_date_only_by_reply(self):
        self.bot.today = lambda: date(2026, 4, 14)
        e, card_id = self.card_for(update(10, text="12.50 boulangerie"))
        self.feed(self.reply("10/04", card_id), flush=False)
        e = self.store.get(e.id)
        self.assertEqual((e.amount_cents, e.original_date), (1250, "2026-04-10T10:15:00+00:00"))
        self.assertEqual(self.api.sent()[-1]["text"], texts.DATE_SAVED.format(id=e.id, date="10.04.2026"))


class AwaitingAmountTest(BotTestCase):
    """After a card asks for an amount, a bare amount sent next fills it in."""

    def test_bare_amount_fills_the_receipt(self):
        e, card_id = self.card_for(update(10, photo=photo_sizes("rcpt-A")))
        self.feed(update(11, text="15.62"))
        self.assertEqual([x.id for x in self.store.all()], [e.id])
        self.assertEqual(self.store.get(e.id).amount_cents, 1562)
        self.assertEqual(self.api.sent("editMessageText")[-1]["message_id"], card_id)
        self.assertEqual(self.api.sent()[-1]["text"], texts.AMOUNT_SAVED.format(id=e.id, amount="15,62 €"))
        # Only once: the next bare amount is a new expense again.
        self.feed(update(12, text="3"))
        self.assertEqual(len(self.store.all()), 2)

    def test_amount_with_a_description_is_a_new_expense(self):
        e, _ = self.card_for(update(10, photo=photo_sizes("rcpt-A")))
        self.feed(update(11, text="12 café"))
        self.assertEqual(len(self.store.all()), 2)
        self.assertIsNone(self.store.get(e.id).amount_cents)

    def test_waiting_expires(self):
        e, _ = self.card_for(update(10, photo=photo_sizes("rcpt-A")))
        self.clock.now += 1801
        self.feed(update(11, text="15.62"))
        self.assertEqual(len(self.store.all()), 2)
        self.assertIsNone(self.store.get(e.id).amount_cents)

    def test_a_forwarded_amount_is_not_taken(self):
        e, _ = self.card_for(update(10, photo=photo_sizes("rcpt-A")))
        self.feed(update(11, origin=from_user(SAM), text="15.62"))
        self.assertEqual(len(self.store.all()), 2)


class TextDateTest(BotTestCase):
    """A date at the end of a text moves the expense to that day, same time of day."""

    def test_text_with_a_date(self):
        self.feed(update(30, text="12.50 boulangerie 01.10", date=epoch(2026, 10, 4, 12)))
        [e] = self.store.all()
        self.assertEqual((e.amount_cents, e.description, e.original_date),
                         (1250, "boulangerie", "2026-10-01T12:00:00+00:00"))
        self.assertIn("Дата: 01.10.2026", self.api.sent()[-1]["text"])

    def test_two_messages_naming_the_same_day_stay_two_expenses(self):
        self.feed(update(31, text="5 café 01.10", date=epoch(2026, 10, 4, 9)))
        self.feed(update(32, text="5 café 01.10", date=epoch(2026, 10, 4, 17)))
        self.assertEqual(len(self.store.all()), 2)

    def test_the_same_message_forwarded_twice_is_one_expense(self):
        origin = from_user(SAM, date=epoch(2026, 10, 4, 9))
        self.feed(update(33, origin=origin, text="5 café вчера"))
        self.feed(update(34, origin=origin, text="5 café вчера"))
        [e] = self.store.all()
        self.assertEqual(e.original_date, "2026-10-03T09:00:00+00:00")


class ButtonsTest(BotTestCase):
    def setUp(self):
        super().setUp()
        self.e, self.card_id = self.card_for(update(10, origin=from_user(SAM), text="40 resto"))

    def press(self, data, sender=ALEX):
        self.api.calls.clear()
        self.feed(callback(data, self.card_id, sender), flush=False)
        self.assertEqual(len(self.api.sent("answerCallbackQuery")), 1)
        edits = self.api.sent("editMessageText")
        return edits[-1] if edits else None

    def test_change_payer(self):
        menu = self.press(f"p:{self.e.id}")
        self.assertIn("Кто платил?", menu["text"])
        labels = [b["text"] for b in buttons(menu)]
        self.assertEqual(labels, ["Alex Example", "✓ Sam Example", texts.BTN_BACK])
        card = self.press(f"P:{self.e.id}:0")
        e = self.store.get(self.e.id)
        self.assertEqual((e.payer, e.payer_confirmed), ("alex", True))
        self.assertIn("Платит: Alex Example\n", card["text"])
        self.assertEqual(self.api.sent("answerCallbackQuery")[0]["text"], texts.TOAST_SAVED)

    def test_toggle_shared(self):
        card = self.press(f"s:{self.e.id}")
        self.assertFalse(self.store.get(self.e.id).is_shared)
        self.assertIn("Тип: личная", card["text"])
        self.assertIn(texts.BTN_PERSONAL, [b["text"] for b in buttons(card)])
        self.press(f"s:{self.e.id}")
        self.assertTrue(self.store.get(self.e.id).is_shared)

    def test_choose_category(self):
        menu = self.press(f"c:{self.e.id}")
        labels = [b["text"] for b in buttons(menu)]
        self.assertIn("Прочее", labels)
        self.assertEqual(len(labels), len(texts.CATEGORIES) + 1)
        index = texts.CATEGORIES.index("leisure")
        card = self.press(f"C:{self.e.id}:{index}")
        self.assertEqual(self.store.get(self.e.id).category, "leisure")
        self.assertIn("Категория: Досуг\n", card["text"])
        menu = self.press(f"c:{self.e.id}")
        self.assertIn("✓ Досуг", [b["text"] for b in buttons(menu)])

    def test_a_refused_answer_still_opens_the_menu(self):
        # Telegram refuses an answer that comes too late; the menu must open anyway.
        self.api.errors["answerCallbackQuery"] = TelegramError(
            "answerCallbackQuery: Bad Request: query is too old and response timeout expired "
            "or query ID is invalid", 400)
        with self.assertLogs("budget.bot", "WARNING"):
            menu = self.press(f"c:{self.e.id}")
        self.assertIn("Выберите категорию", menu["text"])

    def test_mark_reimbursement_and_back(self):
        card = self.press(f"r:{self.e.id}")
        e = self.store.get(self.e.id)
        self.assertEqual((e.is_reimbursement, e.payer, e.paid_to), (True, "sam", "alex"))
        self.assertIn(f"Перевод #{self.e.id}", card["text"])
        self.assertIn(texts.BTN_NOT_REIMBURSEMENT, [b["text"] for b in buttons(card)])
        # Swapping the payer of a reimbursement keeps it between two people.
        self.press(f"P:{self.e.id}:0")
        e = self.store.get(self.e.id)
        self.assertEqual((e.payer, e.paid_to), ("alex", "sam"))
        self.press(f"r:{self.e.id}")
        self.assertFalse(self.store.get(self.e.id).is_reimbursement)

    def test_delete_with_confirmation(self):
        confirm = self.press(f"d:{self.e.id}")
        self.assertIn("Удалить эту трату?", confirm["text"])
        self.assertIsNotNone(self.store.get(self.e.id))
        back = self.press(f"b:{self.e.id}")
        self.assertNotIn("Удалить эту трату?", back["text"])
        done = self.press(f"D:{self.e.id}")
        self.assertIsNone(self.store.get(self.e.id))
        self.assertEqual(done["text"], texts.deleted(self.e.id))
        self.assertEqual(done["reply_markup"], {"inline_keyboard": []})
        self.assertIsNone(self.store.card_expense(ALEX_ID, self.card_id))
        self.press(f"s:{self.e.id}")
        self.assertEqual(self.api.sent("answerCallbackQuery")[0]["text"], texts.TOAST_NOT_FOUND)

    def test_stranger_cannot_press(self):
        self.press(f"s:{self.e.id}", sender=user(STRANGER_ID, "Stranger"))
        self.assertEqual(self.api.sent("answerCallbackQuery")[0]["text"], texts.TOAST_NOT_ALLOWED)
        self.assertTrue(self.store.get(self.e.id).is_shared)

    def test_bad_data(self):
        for data in ("", "x", "s:abc", "P:1:99"):
            self.api.calls.clear()
            self.feed(callback(data, self.card_id), flush=False)
            self.assertEqual(len(self.api.sent("answerCallbackQuery")), 1, data)
        self.assertEqual(self.store.get(self.e.id).payer, "sam")


class CommandsTest(BotTestCase):
    def setUp(self):
        super().setUp()
        # Made-up October: Alex pays 100 shared, Sam 40 shared; Sam pays back 10.
        self.feed(update(1, text="100 courses", date=1791021600),        # 2026-10-03
                  update(2, sender=SAM, text="40 resto", date=1791453600))  # 2026-10-08
        self.store.add_reimbursement("sam", "alex", 1000, datetime(2026, 10, 9, 12, tzinfo=timezone.utc))
        self.bot.today = lambda: date(2026, 10, 15)
        self.api.calls.clear()

    def text_of(self, command, sender=ALEX):
        self.feed(update(90, sender=sender, text=command), flush=False)
        return self.api.sent()[-1]["text"]

    def assert_no_debt_wording(self, text):
        for word in ("Долг", "долг", "должен", "доля", "деление"):
            self.assertNotIn(word, text)

    def test_balance_is_this_months_spending_table(self):
        text = self.text_of("/balance")
        self.assertIn("Кто сколько потратил: октябрь 2026", text)
        rows = table_rows(text)
        self.assertEqual(rows[0], ["€", "Alex Example", "Sam Example"])
        # Who actually paid, not a 50/50 share; the payback is not spending.
        self.assertIn(["Продукты", "100,00", "0,00"], rows)
        self.assertIn(["Итого", "100,00", "40,00"], rows)
        self.assertIn(["общие", "100,00", "40,00"], rows)
        self.assertIn(["личные", "0,00", "0,00"], rows)
        self.assert_no_debt_wording(text)

    def test_balance_counts_only_the_current_month(self):
        self.bot.today = lambda: date(2026, 11, 2)
        text = self.text_of("/balance")
        self.assertIn("ноябрь 2026", text)
        self.assertIn("В этом месяце трат нет.", text)

    def test_report(self):
        text = self.text_of("/report 2026-10")
        self.assertIn("Отчёт: октябрь 2026", text)
        self.assertIn("Кто сколько потратил", text)
        self.assertIn(["Продукты", "100,00", "0,00"], table_rows(text))
        self.assertIn("Переводы друг другу", text)
        self.assertIn("09.10.2026 Sam Example → Alex Example 10,00 €", text)
        self.assert_no_debt_wording(text)

    def test_report_defaults_to_the_current_month(self):
        self.assertIn("Отчёт: октябрь 2026", self.text_of("/report"))

    def test_report_over_several_months(self):
        self.feed(update(3, text="30 courses", date=epoch(2026, 8, 5, 10)))
        for command in ("/report 2026-08 2026-10", "/report 2026-10 2026-08", "/report 2026-08..2026-10"):
            text = self.text_of(command)
            self.assertIn("Отчёт: август – октябрь 2026", text, command)
            self.assertIn(["Продукты", "130,00", "0,00"], table_rows(text, 0))
            by_month = table_rows(text, 1)
            self.assertIn(["август 2026", "30,00", "0,00"], by_month)
            self.assertIn(["сентябрь 2026", "0,00", "0,00"], by_month)
            self.assertIn(["октябрь 2026", "100,00", "40,00"], by_month)
            self.assertIn(["Итого", "130,00", "40,00"], by_month)
            self.assertNotIn("Где можно сэкономить", text)

    def test_report_across_years(self):
        self.assertIn("Отчёт: декабрь 2025 – октябрь 2026", self.text_of("/report 2025-12 2026-10"))

    def test_bad_period(self):
        for command in ("/report 2026-08 x", "/report 2026-08 2026-09 2026-10"):
            self.assertEqual(self.text_of(command), texts.BAD_MONTH, command)

    def test_expenses_left_out_get_their_ids_and_open_buttons(self):
        e, _ = self.card_for(update(4, photo=photo_sizes("rcpt-Z"), date=epoch(2026, 10, 10, 10)))
        self.feed(update(90, text="/balance"), flush=False)
        message = self.api.sent()[-1]
        self.assertIn(f"нет суммы: #{e.id}", message["text"])
        self.assertIn(f"o:{e.id}", [b["callback_data"] for b in buttons(message)])

    def test_report_with_bot_name_and_bad_month(self):
        self.assertIn("Отчёт: октябрь 2026", self.text_of("/report@budget_bot 2026-10"))
        self.assertEqual(self.text_of("/report octobre"), texts.BAD_MONTH)

    def test_help(self):
        self.assertEqual(self.text_of("/start"), texts.HELP)
        self.assertEqual(self.text_of("/whatever"), texts.HELP)

    def test_commands_are_not_expenses(self):
        self.text_of("/balance")
        self.assertFalse(self.bot.has_pending())


class TextsTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(texts.money(123456), "1234,56 €")
        self.assertEqual(texts.money(-5), "−0,05 €")
        self.assertEqual(texts.money(None), "без суммы")

    def test_split_label(self):
        self.assertEqual(texts.split_label(SplitRule.even(KEYS)), "50/50")
        self.assertEqual(texts.split_label(SplitRule.parse("60/40", KEYS)), "60/40")
        self.assertEqual(texts.split_label(SplitRule.parse("2/1", KEYS)), "2/1")

    def test_every_category_has_a_label(self):
        for key in texts.CATEGORIES:
            self.assertIn(key, texts.CATEGORY_LABELS)

    def test_callback_data_fits(self):
        self.assertLessEqual(len(f"C:{10**12}:{len(texts.CATEGORIES)}".encode()), 64)


class RunTest(unittest.TestCase):
    def test_polls_handles_and_flushes(self):
        store = Store()
        api = FakeApi(updates=[[update(1, text="5 café"), update(2, text="6 pain")], []])
        clock = Clock()
        bot = Bot(store, members(), api, SplitRule.even(KEYS), clock=clock, debounce=0)
        polls = iter(range(3))
        run(bot, api, sleep=lambda s: None, should_stop=lambda: next(polls, None) is None)
        methods = [m for m, _ in api.calls]
        self.assertEqual(methods[:2], ["deleteWebhook", "setMyCommands"])
        gets = api.sent("getUpdates")
        self.assertEqual(gets[0]["offset"], None)
        self.assertEqual(gets[1]["offset"], 500003)
        self.assertEqual(len(api.sent()), 1)  # one summary for the two
        store.close()

    def test_short_poll_while_a_batch_waits(self):
        store = Store()
        api = FakeApi(updates=[[update(1, text="5 café")], []])
        bot = Bot(store, members(), api, SplitRule.even(KEYS), clock=Clock(), debounce=100)
        polls = iter(range(2))
        run(bot, api, sleep=lambda s: None, should_stop=lambda: next(polls, None) is None)
        self.assertEqual([p["timeout"] for p in api.sent("getUpdates")], [30, 1])
        store.close()

    def test_network_errors_back_off(self):
        store = Store()
        api = FakeApi()
        api.errors["getUpdates"] = TelegramError("getUpdates: Too Many Requests", 429, retry_after=7)
        slept = []
        polls = iter(range(2))
        with self.assertLogs("budget.bot", level="WARNING"):
            run(Bot(store, members(), api, SplitRule.even(KEYS)), api, sleep=slept.append,
                should_stop=lambda: next(polls, None) is None)
        self.assertEqual(slept, [7])
        store.close()

    def test_a_failing_update_does_not_stop_the_loop(self):
        store = Store()
        api = FakeApi(updates=[[{"update_id": 5, "message": {"message_id": 1, "from": ALEX}},
                                update(2, text="5 café")]])
        bot = Bot(store, members(), api, SplitRule.even(KEYS), clock=Clock(), debounce=0)
        polls = iter(range(1))
        with self.assertLogs("budget.bot", level="ERROR"):
            run(bot, api, sleep=lambda s: None, should_stop=lambda: next(polls, None) is None)
        self.assertEqual(len(store.all()), 1)
        store.close()


class TelegramApiTest(unittest.TestCase):
    TOKEN = "123456:FAKE-token-for-tests"

    def respond(self, payload):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
        return response

    def test_call(self):
        with mock.patch("budget.net.urlopen", return_value=self.respond({"ok": True, "result": [1]})) as urlopen:
            result = TelegramApi(self.TOKEN).call("getUpdates", offset=None, timeout=30)
        self.assertEqual(result, [1])
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/getUpdates"))
        self.assertEqual(json.loads(request.data), {"timeout": 30})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 40)

    def test_slow_call_is_logged(self):
        with mock.patch("budget.net.urlopen", return_value=self.respond({"ok": True, "result": []})), \
                mock.patch("budget.telegram_api.time.monotonic", side_effect=[100.0, 145.0]), \
                self.assertLogs("budget.telegram_api", "WARNING") as logs:
            TelegramApi(self.TOKEN).call("getUpdates", timeout=30)
        self.assertIn("getUpdates took 45.0 s", logs.output[0])
        self.assertNotIn(self.TOKEN, logs.output[0])

    def test_api_error(self):
        payload = {"ok": False, "error_code": 429, "description": "Too Many Requests",
                   "parameters": {"retry_after": 5}}
        with mock.patch("budget.net.urlopen", return_value=self.respond(payload)):
            with self.assertRaises(TelegramError) as ctx:
                TelegramApi(self.TOKEN).call("sendMessage", chat_id=1, text="x")
        self.assertEqual((ctx.exception.code, ctx.exception.retry_after), (429, 5))

    def test_http_error_without_token(self):
        body = io.BytesIO(json.dumps({"ok": False, "error_code": 401, "description": "Unauthorized"}).encode())
        error = urllib.error.HTTPError("https://api.telegram.org/bot" + self.TOKEN + "/getMe", 401,
                                       "Unauthorized", {}, body)
        with mock.patch("budget.net.urlopen", side_effect=error):
            with self.assertRaises(TelegramError) as ctx:
                TelegramApi(self.TOKEN).call("getMe")
        self.assertEqual(ctx.exception.code, 401)
        self.assertNotIn(self.TOKEN, str(ctx.exception))

    def test_network_error(self):
        with mock.patch("budget.net.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(TelegramError) as ctx:
                TelegramApi(self.TOKEN).call("getMe")
        self.assertIn("network error", str(ctx.exception))
        self.assertNotIn(self.TOKEN, str(ctx.exception))


class BotCliTest(unittest.TestCase):
    def run_cli(self, env):
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", err):
            return main(["--env", os.devnull, "bot"]), err.getvalue()

    def test_needs_token(self):
        code, err = self.run_cli(ENV)
        self.assertEqual(code, 2)
        self.assertIn("TELEGRAM_BOT_TOKEN", err)

    def test_needs_member_ids(self):
        code, err = self.run_cli({"TELEGRAM_BOT_TOKEN": "123:fake"})
        self.assertEqual(code, 2)
        self.assertIn("MEMBER_1_TELEGRAM_ID", err)


class ReceiptReadingTest(BotTestCase):
    """The bot with a recognizer: a photo is queued, read, and its card updated."""

    def setUp(self):
        super().setUp()
        from tests.test_recognize import ANSWER, FakeReader, FakeTelegram
        self.reader = FakeReader([ANSWER])
        self.bot.recognizer = Recognizer(self.store, FakeTelegram(), self.reader, clock=self.clock,
                                         today=lambda: date(2026, 10, 4))

    def photo(self, message_id=10, **content):
        return update(message_id, photo=photo_sizes(f"rcpt-{message_id}"), date=epoch(2026, 10, 4, 10), **content)

    def test_a_photo_is_read_and_its_card_updated(self):
        e, card_id = self.card_for(self.photo())
        self.assertIn("Читаю чек", self.api.sent()[-1]["text"])
        self.assertTrue(self.bot.has_work())
        self.bot.recognize_next()
        e = self.store.get(e.id)
        self.assertEqual((e.amount_cents, e.description, e.recognition), (1562, "Supermarché Exemple", "done"))
        edit = self.api.sent("editMessageText")[-1]
        self.assertEqual(edit["message_id"], card_id)
        self.assertIn("Сумма: <b>15,62 €</b>", edit["text"])
        self.assertIn("Товаров на чеке: 4", edit["text"])
        self.assertIn("Карта: •••• 1234", edit["text"])
        notice = self.api.sent()[-1]
        self.assertIn(f"Прочитал чек #{e.id}", notice["text"])
        self.assertIn("• FRAISES 500G — 6,90 €", notice["text"])
        self.assertEqual(notice["reply_parameters"]["message_id"], card_id)
        self.assertNotIn(ALEX_ID, self.bot.awaiting)
        self.assertFalse(self.bot.has_work())

    def test_an_unreadable_receipt_asks_for_the_amount(self):
        self.reader.answers = [GeminiError("Gemini 400: bad image")]
        e, _ = self.card_for(self.photo())
        with self.assertLogs("budget.recognize", "WARNING"):
            self.bot.recognize_next()
        self.assertIn("Не получилось прочитать чек", self.api.sent("editMessageText")[-1]["text"])
        self.assertEqual(self.api.sent()[-1]["text"], texts.recognition_failed(self.store.get(e.id)))
        self.feed(update(11, text="15.62"))
        self.assertEqual(self.store.get(e.id).amount_cents, 1562)

    def test_an_amount_typed_before_reading_is_kept(self):
        e, _ = self.card_for(self.photo())
        self.feed(update(11, text="15.00"))
        self.bot.recognize_next()
        self.assertEqual(self.store.get(e.id).amount_cents, 1500)
        self.assertIn("Оставил вашу сумму", self.api.sent()[-1]["text"])

    def test_only_receipts_are_queued(self):
        self.feed(self.photo(10), update(11, text="5 café"), self.photo(12, caption="вернул 32"))
        self.assertEqual([e.recognition for e in sorted(self.store.all(), key=lambda e: e.message_id)],
                         ["pending", None, None])


if __name__ == "__main__":
    unittest.main()
