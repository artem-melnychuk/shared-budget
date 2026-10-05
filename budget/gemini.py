"""Reading a receipt with the Gemini API (`generateContent`), standard library only.

The free tier is enough for a household (a few receipts a day), but Google may use
free-tier content to improve its products: the owner accepted that for receipts.
The API key travels in a header, never in the URL, so errors can't leak it.
"""

import base64
import json
import re
import urllib.error
import urllib.request

from budget import net

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# The cheapest stable model, with the largest free daily quota; GEMINI_MODEL overrides it.
DEFAULT_MODEL = "gemini-3.5-flash-lite"

SYSTEM = """You read photos and PDFs of shop receipts, mostly French, and return their data as JSON.

- total: the amount actually paid, the line labelled TOTAL, TOTAL TTC, NET A PAYER, \
RESTE A PAYER, MONTANT or A PAYER. Not a subtotal, not "TOTAL HORS PROMOTION" when a \
lower amount was paid, not the TVA breakdown, not a loyalty balance (SOLDE, CAGNOTTE, \
points, euros acquis) and not the change given back (RENDU).
- date: the purchase date printed on the receipt, as YYYY-MM-DD. French receipts write \
dates as DD/MM/YYYY or DD/MM/YY. A loyalty-balance date is not the purchase date.
- merchant: the shop or brand name as printed at the top, short (e.g. "Monoprix").
- card_last4: the last 4 digits of the payment card if printed (e.g. "XXXX XXXX XXXX 1234").
- items: every product line with the amount paid for it (quantity x unit price \
already applied). A discount line (REMISE, PROMO, BON) is an item with a negative price. \
Do not list totals, payments, taxes or loyalty lines as items. Category headers such \
as FRUITS/LEGUMES are not items.
- Never guess. Use "" for text you can't read and 0 for a number you can't read.
- is_receipt is false when the image is not a receipt, invoice or payment proof."""

PROMPT = "Read this receipt."

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_receipt": {"type": "boolean"},
        "merchant": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD, or empty"},
        "total": {"type": "number", "description": "amount paid in currency units, 0 if unreadable"},
        "currency": {"type": "string", "description": "ISO 4217 code such as EUR"},
        "card_last4": {"type": "string", "description": "4 digits, or empty"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number", "description": "1 when not printed"},
                    "price": {"type": "number", "description": "amount paid for the line; negative for a discount"},
                },
                "required": ["name", "quantity", "price"],
            },
        },
    },
    "required": ["is_receipt", "merchant", "date", "total", "currency", "card_last4", "items"],
}

RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class GeminiError(Exception):
    """`retryable`: worth trying again later (quota, overload, network, a garbled answer)."""

    def __init__(self, message: str, retryable: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def _retry_delay(error: dict) -> float | None:
    """`RetryInfo.retryDelay` ("37s") from a Google API error body, if present."""
    for detail in error.get("details") or []:
        delay = detail.get("retryDelay")
        if delay and (m := re.fullmatch(r"(\d+(?:\.\d+)?)s", delay)):
            return float(m.group(1))
    return None


def _json_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):  # tolerate a fenced answer
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


class Gemini:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 90):
        self._key = api_key
        self.model = model
        self.timeout = timeout

    def read_receipt(self, data: bytes, mime_type: str) -> dict:
        """The receipt fields as a dict shaped by RECEIPT_SCHEMA; raises GeminiError."""
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(data).decode()}},
                {"text": PROMPT},
            ]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": RECEIPT_SCHEMA,
            },
        }
        request = urllib.request.Request(
            API_URL.format(model=self.model), data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._key})
        try:
            with net.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            try:
                error = json.load(e).get("error") or {}
            except (ValueError, OSError):
                error = {}
            message = error.get("message") or f"HTTP {e.code}"
            raise GeminiError(f"Gemini {e.code}: {message}", e.code in RETRYABLE_HTTP,
                              _retry_delay(error)) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            raise GeminiError(f"Gemini network error: {type(e).__name__}: {reason}", retryable=True) from None

        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("promptFeedback") or {}).get("blockReason") or "no answer"
            raise GeminiError(f"Gemini returned nothing: {reason}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            result = _json_text(text)
        except ValueError:
            finish = candidates[0].get("finishReason")
            raise GeminiError(f"Gemini answer is not JSON (finishReason {finish})", retryable=True) from None
        if not isinstance(result, dict):
            raise GeminiError("Gemini answer is not a JSON object", retryable=True)
        return result
