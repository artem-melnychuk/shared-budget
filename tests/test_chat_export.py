import unittest
from datetime import datetime, timezone
from pathlib import Path

from budget.chat_export import flatten_text, load_export, parse_export

EXPORT = Path(__file__).parent / "fixtures" / "result.json"


class ChatExportTest(unittest.TestCase):
    def setUp(self):
        self.messages = {m.message_id: m for m in parse_export(load_export(EXPORT))}

    def test_flatten_text(self):
        self.assertEqual(flatten_text("a"), "a")
        self.assertEqual(flatten_text(["35 ", {"type": "bold", "text": "courses"}, "!"]), "35 courses!")
        self.assertEqual(flatten_text(None), "")

    def test_skips_service_stickers_and_empty(self):
        self.assertEqual(sorted(self.messages), [2, 3, 4, 5, 6, 8, 9])

    def test_text_entry(self):
        m = self.messages[2]
        self.assertEqual((m.source, m.chat_id, m.kind), ("export", 4242, "text"))
        self.assertEqual((m.author_user_id, m.author_name), (1002, "Sam Example"))
        self.assertEqual(m.original_date, datetime(2026, 3, 14, 10, 15, tzinfo=timezone.utc))
        self.assertIsNone(m.sender_user_id)

    def test_entity_text_and_local_date(self):
        m = self.messages[4]
        self.assertEqual(m.text, "35,80 courses marché")
        # No date_unixtime: local Nice time, UTC+1 in March.
        self.assertEqual(m.original_date, datetime(2026, 3, 15, 17, 30, tzinfo=timezone.utc))

    def test_photo_and_file(self):
        photo, pdf = self.messages[3], self.messages[6]
        self.assertEqual((photo.kind, photo.file_path), ("photo", "photos/photo_1@14-03-2026_12-00-00.jpg"))
        self.assertIsNone(photo.file_unique_id)
        self.assertEqual((pdf.kind, pdf.mime_type, pdf.file_name), ("document", "application/pdf", "e-ticket.pdf"))

    def test_media_not_included(self):
        m = self.messages[9]
        self.assertEqual(m.kind, "photo")
        self.assertIsNone(m.file_path)


if __name__ == "__main__":
    unittest.main()
