import os
import tempfile
import unittest
from pathlib import Path

from budget.chat_export import load_export
from budget.ingest import import_export, ingest_update
from budget.storage import Store
from tests.fakes import (ALEX, SAM, STRANGER_ID, T_ORIGINAL, from_hidden,
                            from_user, members, photo_sizes, update, user)

EXPORT = Path(__file__).parent / "fixtures" / "result.json"


class IngestUpdateTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.members = members()

    def tearDown(self):
        self.store.close()

    def add(self, upd):
        return ingest_update(self.store, self.members, upd)

    def test_forwarded_photo_of_the_other_persons_receipt(self):
        r = self.add(update(10, sender=ALEX, origin=from_user(SAM), photo=photo_sizes("rcpt-A")))
        self.assertEqual(r.status, "added")
        e = self.store.get(r.expense_id)
        self.assertEqual((e.author, e.sender, e.payer), ("sam", "alex", "sam"))
        self.assertFalse(e.payer_confirmed)
        self.assertTrue(e.is_shared)
        self.assertIsNone(e.amount_cents)
        self.assertEqual(e.currency, "EUR")
        self.assertEqual(e.original_date, "2026-03-14T10:15:00+00:00")
        self.assertEqual(e.file_unique_id, "rcpt-A")

    def test_caption_amount_is_used(self):
        r = self.add(update(10, photo=photo_sizes("rcpt-A"), caption="23,90 pharmacie"))
        e = self.store.get(r.expense_id)
        self.assertEqual((e.amount_cents, e.description), (2390, "pharmacie"))

    def test_hidden_author_resolved_by_configured_name(self):
        r = self.add(update(11, sender=ALEX, origin=from_hidden("Sam Example"), text="35 courses"))
        e = self.store.get(r.expense_id)
        self.assertEqual((e.author, e.payer, e.amount_cents, e.description), ("sam", "sam", 3500, "courses"))
        self.assertIsNone(e.author_user_id)

    def test_unknown_forward_author_defaults_payer_to_forwarder(self):
        r = self.add(update(12, sender=SAM, origin=from_hidden("A Shop"), text="15 livraison"))
        e = self.store.get(r.expense_id)
        self.assertEqual((e.author, e.sender, e.payer), (None, "sam", "sam"))

    def test_direct_text(self):
        r = self.add(update(13, sender=SAM, text="12.50 boulangerie"))
        e = self.store.get(r.expense_id)
        self.assertEqual((e.author, e.payer, e.forwarded, e.amount_cents), ("sam", "sam", False, 1250))

    def test_chat_text_is_ignored(self):
        r = self.add(update(14, text="on mange où ce soir ?"))
        self.assertEqual((r.status, r.reason), ("ignored", "text is not an amount"))
        self.assertEqual(self.store.all(), [])

    def test_stranger_is_ignored(self):
        r = self.add(update(15, sender=user(STRANGER_ID, "Stranger"), text="10 hack"))
        self.assertEqual((r.status, r.reason), ("ignored", "sender is not a member"))

    def test_same_photo_forwarded_twice_by_each_member(self):
        first = self.add(update(20, sender=ALEX, origin=from_user(SAM), photo=photo_sizes("rcpt-B")))
        again = self.add(update(30, sender=SAM, photo=photo_sizes("rcpt-B")))
        self.assertEqual(again.status, "duplicate")
        self.assertEqual(again.expense_id, first.expense_id)
        self.assertEqual(len(self.store.all()), 1)

    def test_redelivered_update(self):
        upd = update(21, photo=photo_sizes("rcpt-C"))
        self.add(upd)
        self.assertEqual(self.add(upd).status, "duplicate")

    def test_same_text_forwarded_twice(self):
        self.add(update(22, sender=ALEX, origin=from_user(SAM), text="12.50 boulangerie"))
        r = self.add(update(40, sender=SAM, origin=from_hidden("Sammy"), text="12.50 boulangerie"))
        self.assertEqual(r.status, "duplicate")

    def test_same_amount_at_another_time_is_new(self):
        self.add(update(22, origin=from_user(SAM), text="12.50 boulangerie"))
        r = self.add(update(23, origin=from_user(SAM, date=T_ORIGINAL + 3600), text="12.50 boulangerie"))
        self.assertEqual(r.status, "added")

    def test_album_photos_are_separate_rows(self):
        for i, unique in enumerate(("p1", "p2", "p3")):
            self.add(update(50 + i, origin=from_user(SAM), photo=photo_sizes(unique), media_group_id="album-7"))
        group = self.store.media_group("album-7")
        self.assertEqual([e.file_unique_id for e in group], ["p1", "p2", "p3"])

    def test_change_payer_and_shared(self):
        r = self.add(update(60, origin=from_user(SAM), text="80 resto"))
        self.store.set_payer(r.expense_id, "alex")
        self.store.set_shared(r.expense_id, False)
        e = self.store.get(r.expense_id)
        self.assertEqual((e.author, e.payer, e.payer_confirmed, e.is_shared), ("sam", "alex", True, False))


class ImportExportTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.members = members()
        self.data = load_export(EXPORT)

    def tearDown(self):
        self.store.close()

    def test_import(self):
        s = import_export(self.store, self.members, self.data)
        # 2 text, 3 photo, 4 text, 6 pdf, 9 photo; 5 is chat, 8 is not a member.
        self.assertEqual((s.added, s.duplicate, s.ignored), (5, 0, 2))
        self.assertEqual(s.reasons, {"text is not an amount": 1, "author is not a member": 1})
        by_msg = {e.message_id: e for e in self.store.all()}
        self.assertEqual((by_msg[4].author, by_msg[4].amount_cents, by_msg[4].description),
                         ("alex", 3580, "courses marché"))
        self.assertEqual(by_msg[2].payer, "sam")

    def test_reimport_is_idempotent(self):
        import_export(self.store, self.members, self.data)
        s = import_export(self.store, self.members, self.data)
        self.assertEqual((s.added, s.duplicate), (0, 5))

    def test_export_and_forward_of_the_same_message_count_once(self):
        # Message 2 of the export ("12.50 boulangerie" by Sam at 10:15 UTC), forwarded by Alex.
        ingest_update(self.store, self.members,
                      update(70, sender=ALEX, origin=from_user(SAM), text="12.50 boulangerie"))
        s = import_export(self.store, self.members, self.data)
        self.assertEqual((s.added, s.duplicate), (4, 1))
        self.assertEqual(len(self.store.all()), 5)


class StoreFileTest(unittest.TestCase):
    def test_data_survives_reopening(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budget.db")
            store = Store(path)
            ingest_update(store, members(), update(1, text="5 café"))
            store.close()
            store = Store(path)
            self.assertEqual([e.amount_cents for e in store.all()], [500])
            store.close()


if __name__ == "__main__":
    unittest.main()
