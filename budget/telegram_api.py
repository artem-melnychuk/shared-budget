"""Minimal Telegram Bot API client on the standard library.

The bot needs a handful of methods; a thin `call()` keeps the dependency list
empty and lets tests swap in a fake with the same `call()` signature.
"""

import json
import urllib.error
import urllib.request

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    def __init__(self, description: str, code: int | None = None, retry_after: int | None = None):
        super().__init__(description)
        self.description = description
        self.code = code
        self.retry_after = retry_after

    @property
    def not_modified(self) -> bool:
        return "message is not modified" in self.description


class TelegramApi:
    def __init__(self, token: str, timeout: float = 10):
        self._token = token
        self.timeout = timeout

    def call(self, method: str, **params):
        """POST `params` as JSON; return `result` or raise `TelegramError`.

        Errors never include the URL, which holds the token.
        """
        body = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
        request = urllib.request.Request(
            API_URL.format(token=self._token, method=method), data=body,
            headers={"Content-Type": "application/json"})
        # Long polling holds the request open for `timeout` seconds.
        wait = self.timeout + params.get("timeout", 0)
        try:
            with urllib.request.urlopen(request, timeout=wait) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            try:
                payload = json.load(e)
            except (ValueError, OSError):
                raise TelegramError(f"{method}: HTTP {e.code}", e.code) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            raise TelegramError(f"{method}: network error: {type(e).__name__}: {reason}") from None
        if not payload.get("ok"):
            params_ = payload.get("parameters") or {}
            raise TelegramError(f"{method}: {payload.get('description', 'error')}",
                                payload.get("error_code"), params_.get("retry_after"))
        return payload["result"]
