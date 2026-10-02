import unittest
from datetime import datetime, timezone

from budget.telegram_update import parse_update
from tests.fakes import (ALEX, ALEX_ID, SAM, SAM_ID, T_FORWARD, T_ORIGINAL,
                            from_hidden, from_user, photo_sizes, update)

ORIGINAL = datetime(2026, 3, 14, 10, 15, tzinfo=timezone.utc)
FORWARDED_AT = datetime(2026, 4, 14, 10, 15, tzinfo=timezone.utc)


class ParseUpdateTest(unittest.TestCase):
    def test_forward_from_visible_user(self):
        msg = parse_update(update(10, sender=ALEX, origin=from_user(SAM),
                                  photo=photo_sizes("rcpt-A"), caption="12.50 boulangerie"))
        self.assertEqual(msg.kind, "photo")
        self.assertTrue(msg.forwarded)
        self.assertEqual((msg.author_user_id, msg.author_name), (SAM_ID, "Sam Example"))
        self.assertEqual(msg.sender_user_id, ALEX_ID)
        self.assertEqual(msg.original_date, ORIGINAL)
        self.assertEqual(msg.text, "12.50 boulangerie")

    def test_largest_photo_size_is_kept(self):
        msg = parse_update(update(10, photo=photo_sizes("rcpt-A")))
        self.assertEqual((msg.file_unique_id, msg.file_id), ("rcpt-A", "big-rcpt-A"))

    def test_forward_from_hidden_user(self):
        msg = parse_update(update(11, origin=from_hidden("Sammy"), text="35 courses"))
        self.assertTrue(msg.forwarded)
        self.assertIsNone(msg.author_user_id)
        self.assertEqual(msg.author_name, "Sammy")
        self.assertEqual(msg.original_date, ORIGINAL)

    def test_forward_from_channel(self):
        origin = {"type": "channel", "chat": {"id": -100123, "type": "channel", "title": "Shop news"},
                  "message_id": 5, "date": T_ORIGINAL}
        msg = parse_update(update(12, origin=origin, text="9.99 promo"))
        self.assertIsNone(msg.author_user_id)
        self.assertEqual(msg.author_name, "Shop news")

    def test_direct_message(self):
        msg = parse_update(update(13, sender=SAM, text="4,20 café"))
        self.assertFalse(msg.forwarded)
        self.assertEqual((msg.author_user_id, msg.sender_user_id), (SAM_ID, SAM_ID))
        self.assertEqual(msg.original_date, FORWARDED_AT)
        self.assertEqual(msg.chat_id, SAM_ID)

    def test_pdf_document(self):
        doc = {"file_id": "doc-1", "file_unique_id": "udoc-1", "file_name": "facture.pdf",
               "mime_type": "application/pdf", "file_size": 20000}
        msg = parse_update(update(14, document=doc, caption="e-receipt"))
        self.assertEqual(msg.kind, "document")
        self.assertEqual((msg.file_unique_id, msg.file_name, msg.text), ("udoc-1", "facture.pdf", "e-receipt"))

    def test_other_documents_are_skipped(self):
        doc = {"file_id": "z", "file_unique_id": "uz", "file_name": "a.zip", "mime_type": "application/zip"}
        self.assertIsNone(parse_update(update(15, document=doc)))

    def test_album_keeps_media_group_id(self):
        first = parse_update(update(16, photo=photo_sizes("p1"), media_group_id="album-1", caption="2 pages"))
        second = parse_update(update(17, photo=photo_sizes("p2"), media_group_id="album-1"))
        self.assertEqual((first.media_group_id, second.media_group_id), ("album-1", "album-1"))
        self.assertIsNone(second.text)

    def test_nothing_to_log(self):
        self.assertIsNone(parse_update({"update_id": 1}))
        self.assertIsNone(parse_update({"update_id": 2, "edited_message": update(1, text="5 x")["message"]}))
        self.assertIsNone(parse_update(update(18, sticker={"file_id": "s", "file_unique_id": "us"})))


if __name__ == "__main__":
    unittest.main()
