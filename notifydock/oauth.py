"""Per-account OAuth tokens stored only in macOS Keychain.

The Mac app itself never receives or stores provider credentials.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import urllib.error

from .http import AuthRequired, CollectorError, NO_REDIRECTS
from .keychain import Keychain, SecretUnavailable


def form_post(url: str, fields: dict[str, str], timeout: int = 20) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json", "User-Agent": "NotificationWidget/0.1"}, method="POST")
    try:
        with NO_REDIRECTS.open(request, timeout=timeout) as resp:
            return json.loads(resp.read(64 * 1024))
    except urllib.error.HTTPError as exc:
        # Never copy OAuth error bodies/tokens into logs or snapshots.
        if exc.code in (400, 401, 403):
            raise AuthRequired("OAuth authorization expired or rejected") from None
        raise CollectorError(f"OAuth endpoint HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        raise CollectorError("OAuth endpoint unavailable or response invalid") from None


def store_token(keychain: Keychain, ref: str, response: dict, *,
                client_id: str, token_url: str, client_secret: str = "", scope: str = "") -> None:
    if "access_token" not in response:
        raise AuthRequired("Provider did not issue an access token")
    payload = {
        "access_token": response["access_token"],
        "refresh_token": response.get("refresh_token", ""),
        "expires_at": int(time.time()) + max(0, int(response.get("expires_in", 3600))) - 30,
        "client_id": client_id, "client_secret": client_secret,
        "token_url": token_url, "scope": scope,
    }
    keychain.set(ref, json.dumps(payload, separators=(",", ":")))


def access_token(keychain: Keychain, ref: str) -> str:
    try:
        raw = keychain.get(ref)
    except SecretUnavailable as exc:
        raise AuthRequired(str(exc)) from None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not dict")
    except ValueError:
        # Also support raw access tokens for e.g. manual testing, without refresh.
        if raw:
            return raw
        raise AuthRequired("No OAuth credential stored") from None
    if data.get("expires_at", 0) >= int(time.time()) + 60:
        return data["access_token"]
    if not data.get("refresh_token"):
        raise AuthRequired("OAuth token expired; reconnect account")
    fields = {"client_id": data["client_id"], "grant_type": "refresh_token",
              "refresh_token": data["refresh_token"]}
    if data.get("client_secret"):
        fields["client_secret"] = data["client_secret"]
    if data.get("scope") and "microsoftonline.com" in data["token_url"]:
        fields["scope"] = data["scope"]
    fresh = form_post(data["token_url"], fields)
    # Providers may rotate refresh tokens or omit unchanged refresh token.
    if not fresh.get("refresh_token"):
        fresh["refresh_token"] = data["refresh_token"]
    try:
        store_token(keychain, ref, fresh, client_id=data["client_id"],
                    token_url=data["token_url"], client_secret=data.get("client_secret", ""),
                    scope=data.get("scope", ""))
    except SecretUnavailable:
        raise AuthRequired("Unable to save renewed OAuth credential to Keychain") from None
    return fresh["access_token"]
