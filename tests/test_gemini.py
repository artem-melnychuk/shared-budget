import base64
import io
import json
import unittest
import urllib.error
from unittest import mock

from budget.gemini import RECEIPT_SCHEMA, Gemini, GeminiError

KEY = "fake-gemini-key-for-tests"


def respond(payload):
    response = mock.MagicMock()
    response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return response


def answer(text, *extra_parts):
    return {"candidates": [{"content": {"parts": [*extra_parts, {"text": text}]}, "finishReason": "STOP"}]}


def http_error(code, body):
    return urllib.error.HTTPError("https://generativelanguage.googleapis.com/...", code, "error", {},
                                  io.BytesIO(json.dumps(body).encode()))


class GeminiTest(unittest.TestCase):
    def read(self, **patch_kwargs):
        with mock.patch("budget.net.urlopen", **patch_kwargs) as urlopen:
            result = Gemini(KEY, "gemini-test-model").read_receipt(b"\xff\xd8 jpeg", "image/jpeg")
        return result, urlopen

    def test_request_and_answer(self):
        result, urlopen = self.read(return_value=respond(answer('{"is_receipt": true}')))
        self.assertEqual(result, {"is_receipt": True})
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/models/gemini-test-model:generateContent"))
        self.assertNotIn(KEY, request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), KEY)
        body = json.loads(request.data)
        image = body["contents"][0]["parts"][0]["inline_data"]
        self.assertEqual((image["mime_type"], base64.b64decode(image["data"])), ("image/jpeg", b"\xff\xd8 jpeg"))
        config = body["generationConfig"]
        self.assertEqual((config["responseMimeType"], config["responseJsonSchema"]),
                         ("application/json", RECEIPT_SCHEMA))

    def test_thoughts_and_fences_are_skipped(self):
        result, _ = self.read(return_value=respond(answer('```json\n{"is_receipt": false}\n```',
                                                          {"text": "let me look", "thought": True})))
        self.assertEqual(result, {"is_receipt": False})

    def test_quota_is_retryable_with_delay(self):
        body = {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED",
                          "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}}
        with self.assertRaises(GeminiError) as ctx:
            self.read(side_effect=http_error(429, body))
        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(ctx.exception.retry_after, 37.0)
        self.assertNotIn(KEY, str(ctx.exception))

    def test_bad_request_is_final(self):
        with self.assertRaises(GeminiError) as ctx:
            self.read(side_effect=http_error(400, {"error": {"code": 400, "message": "Unsupported MIME type"}}))
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("Unsupported MIME type", str(ctx.exception))

    def test_network_error_is_retryable(self):
        with self.assertRaises(GeminiError) as ctx:
            self.read(side_effect=urllib.error.URLError("timed out"))
        self.assertTrue(ctx.exception.retryable)

    def test_empty_or_garbled_answers(self):
        with self.assertRaises(GeminiError) as ctx:
            self.read(return_value=respond({"promptFeedback": {"blockReason": "SAFETY"}}))
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("SAFETY", str(ctx.exception))
        with self.assertRaises(GeminiError) as ctx:
            self.read(return_value=respond(answer("not json")))
        self.assertTrue(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
