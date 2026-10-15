"""Read-oriented HTTP utility; changes to user read state are prohibited by convention.

Only the Jira approximate-count API and OAuth token endpoints use POST. No
message-update, notification-update, or mark-read endpoints are present.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any


class CollectorError(RuntimeError):
    status = "error"

    def __init__(self, message: str = "Provider request failed", retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class AuthRequired(CollectorError):
    status = "auth_required"


class Unsupported(CollectorError):
    status = "unsupported"


class Unavailable(CollectorError):
    status = "unavailable"


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward bearer tokens or HTTP basic secrets across a redirect."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


NO_REDIRECTS = urllib.request.build_opener(RejectRedirects())


def request_json(url: str, headers: dict[str, str] | None = None,
                 data: dict[str, Any] | None = None,
                 timeout: int = 16) -> tuple[Any, dict[str, str]]:
    """GET by default. JSON POST only for explicitly specified operations."""
    req_headers = {"Accept": "application/json", "User-Agent": "NotificationWidget/0.1", **(headers or {})}
    method = "GET" if data is None else "POST"
    body = None
    if data is not None:
        req_headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with NO_REDIRECTS.open(request, timeout=timeout) as response:
            raw = response.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                raise CollectorError("Provider response exceeds size limit")
            return json.loads(raw), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        retry_after = 0
        try:
            retry_after = max(0, min(86400, int(exc.headers.get("Retry-After", "0"))))
        except (TypeError, ValueError):
            pass
        if exc.code == 403 and (retry_after or exc.headers.get("X-RateLimit-Remaining") == "0"):
            try:
                reset = max(0, int(exc.headers.get("X-RateLimit-Reset", "0")) - int(time.time()))
                retry_after = max(retry_after, min(reset, 86400))
            except (ValueError, TypeError):
                pass
            raise CollectorError("Provider rate limit reached (HTTP 403)", retry_after or 60) from None
        if exc.code in (401, 403):
            raise AuthRequired(f"Provider rejected credentials or permission (HTTP {exc.code})", retry_after) from None
        if exc.code == 429:
            raise CollectorError("Provider rate limit reached", retry_after or 60) from None
        raise CollectorError(f"Provider HTTP {exc.code}", retry_after) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CollectorError("Network unavailable or timed out") from None
    except (ValueError, UnicodeError):
        raise CollectorError("Provider returned malformed JSON") from None


def require_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise CollectorError(f"Provider omitted valid {label}")
    return value


def parse_next_link(header: str, allowed_prefix: str) -> str | None:
    for section in header.split(","):
        if 'rel="next"' in section:
            match = re.search(r"<([^>]+)>", section)
            if match and match.group(1).startswith(allowed_prefix):
                return match.group(1)
            raise CollectorError("Unexpected pagination destination")
    return None
