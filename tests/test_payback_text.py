"""A debt paid back, written as text in Telegram or found in a chat export."""

import unittest

from budget.balance import Debt, SplitRule, compute_balance
from budget.chat_export import parse_export
from budget.ingest import ingest, ingest_update
from budget.storage import Store
from tests.fakes import ALEX, SAM, from_hidden, from_user, members, photo_sizes, update
from tests.test_bot import AmountReplyTest, BotTestCase

KEYS = ["alex", "sam"]


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.members = members()

    def tearDown(self):
        self.store.close()

    def add(self, upd):
        return self.store.get(ingest_update(self.store, self.members, upd).expense_id)

    def test_direct_text(self):
        e = self.add(update(1, sender=SAM, text="вернул 32"))
        self.assertEqual((e.is_reimbursement, e.payer, e.paid_to, e.amount_cents, e.is_shared),
                         (True, "sam", "alex", 3200, False))

    def test_forwarded_from_the_other_member(self):
        e = self.add(update(2, sender=ALEX, origin=from_user(SAM), text="remboursé 32,50"))
        self.assertEqual((e.payer, e.paid_to), ("sam", "alex"))
        e = self.add(update(3, sender=ALEX, origin=from_hidden("Sammy", date=1773483400), text="32 remboursement"))
        self.assertEqual((e.payer, e.paid_to), ("sam", "alex"))

    def test_settles_the_balance(self):
        self.add(update(4, sender=ALEX, text="64 courses"))
        self.add(update(5, sender=SAM, text="remboursé 32"))
        self.assertEqual(compute_balance(self.store.all(), SplitRule.even(KEYS)).debts, [])

    def test_photo_caption(self):
        e = self.add(update(6, sender=SAM, photo=photo_sizes("transfer-1"), caption="вернула долг 20"))
        self.assertEqual((e.is_reimbursement, e.paid_to, e.amount_cents), (True, "alex", 2000))

    def test_from_a_chat_export(self):
        data = {"id": 1, "messages": [
            {"id": 1, "type": "message", "date": "2026-10-05T10:00:00", "date_unixtime": "1791187200",
             "from": "Sam Example", "from_id": "user1002", "text": "remboursé 12"}]}
        [msg] = parse_export(data)
        e = self.store.get(ingest(self.store, self.members, msg).expense_id)
        self.assertEqual((e.is_reimbursement, e.payer, e.paid_to), (True, "sam", "alex"))

    def test_a_forwarded_payback_counts_once(self):
        self.add(update(7, sender=SAM, text="вернул 32"))
        r = ingest_update(self.store, self.members, update(8, sender=ALEX, origin=from_user(SAM, date=1776161700),
                                                           text="вернул 32"))
        self.assertEqual(r.status, "duplicate")


class BotTest(BotTestCase):
    def test_payback_card(self):
        self.feed(update(1, sender=SAM, text="вернул 32"))
        card = self.api.sent()[-1]["text"]
        self.assertIn("Перевод #", card)
        self.assertIn("От кого: Sam Example", card)
        self.assertIn("Кому: Alex Example", card)

    def test_payback_in_a_batch_summary(self):
        self.feed(update(1, sender=SAM, text="вернул 32"), update(2, sender=SAM, text="5 café"))
        self.assertIn("перевод Sam Example → Alex Example", self.api.sent()[-1]["text"])

    def test_reply_to_a_card_can_mark_a_payback(self):
        e, card_id = self.card_for(update(10, photo=photo_sizes("transfer-2")))
        self.feed(AmountReplyTest.reply(self, "remboursé 32", card_id), flush=False)
        e = self.store.get(e.id)
        self.assertEqual((e.is_reimbursement, e.paid_to, e.amount_cents), (True, "sam", 3200))


if __name__ == "__main__":
    unittest.main()
