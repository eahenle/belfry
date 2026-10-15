"""OAuth onboarding tools, with tokens stored in Keychain (never in files)."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .http import AuthRequired, CollectorError, NO_REDIRECTS
from .keychain import Keychain
from .oauth import form_post, store_token


class CallbackHandler(BaseHTTPRequestHandler):
    server: "CallbackServer"

    def do_GET(self) -> None:
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        self.server.result = {k: v[0] for k, v in params.items() if v}
        if urllib.parse.urlsplit(self.path).path != "/oauth/callback":
            self.send_response(404)
        elif self.server.result.get("state") != self.server.state:
            self.send_response(403)
        else:
            self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Notification Widget: you may close this tab and return to your terminal.\n")

    def log_message(self, format: str, *args: object) -> None:
        # Callback URLs may contain authorization codes. Do not log them.
        pass


class CallbackServer(HTTPServer):
    result: dict[str, str]
    state: str


def google_login(keychain: Keychain, ref: str, client_file: Path) -> None:
    document = json.loads(client_file.read_text(encoding="utf-8"))
    app = document.get("installed")
    if not isinstance(app, dict) or not app.get("client_id") or not app.get("client_secret"):
        raise ValueError("Expected Google OAuth Desktop Client JSON with 'installed' object")
    client_id = app["client_id"]
    client_secret = app["client_secret"]
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(32)
    server = CallbackServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 180
    server.state = state
    server.result = {}
    redirect = f"http://127.0.0.1:{server.server_port}/oauth/callback"
    scope = "https://www.googleapis.com/auth/gmail.labels"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": scope, "access_type": "offline", "prompt": "consent",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state})
    print("Opening Google sign-in browser… (Desktop OAuth client required)")
    if not webbrowser.open(url):
        print(f"Open this URL manually: {url}")
    server.handle_request()
    server.server_close()
    result = server.result
    if result.get("state") != state or not result.get("code"):
        raise AuthRequired("Google OAuth callback failed, timed out, or was denied")
    tokens = form_post("https://oauth2.googleapis.com/token", {
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
    if not tokens.get("refresh_token"):
        raise AuthRequired("Google did not provide a refresh token; revoke old grant and retry")
    store_token(keychain, ref, tokens, client_id=client_id,
                client_secret=client_secret, token_url="https://oauth2.googleapis.com/token")
    print(f"Google authorization saved to macOS Keychain reference {ref!r}.")


def _device_form_post(url: str, fields: dict[str, str]) -> tuple[dict, int]:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                method="POST")
    try:
        with NO_REDIRECTS.open(request, timeout=20) as response:
            return json.loads(response.read(65536)), response.status
    except urllib.error.HTTPError as exc:
        # Inspect errors only in memory to implement the standard OAuth device flow.
        try:
            obj = json.loads(exc.read(65536))
        except ValueError:
            obj = {}
        return obj, exc.code


def microsoft_login(keychain: Keychain, ref: str, client_id: str, tenant: str = "common") -> None:
    if not client_id:
        raise ValueError("Microsoft public-client application ID required")
    if tenant not in ("common", "organizations", "consumers") and not (len(tenant) == 36 and tenant.count("-") == 4):
        raise ValueError("tenant must be common, organizations, consumers, or a tenant UUID")
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    scope = "offline_access Mail.ReadBasic"
    instructions = form_post(base + "/devicecode", {"client_id": client_id, "scope": scope})
    code = instructions["device_code"]
    print(f"Open {instructions['verification_uri']} and enter code {instructions['user_code']}")
    print("Only approve if this is the Microsoft account you intend to connect.")
    deadline = time.monotonic() + min(900, int(instructions.get("expires_in", 900)))
    interval = max(5, int(instructions.get("interval", 5)))
    while time.monotonic() < deadline:
        time.sleep(interval)
        response, status = _device_form_post(base + "/token", {
            "client_id": client_id, "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": code})
        if status == 200 and response.get("access_token"):
            store_token(keychain, ref, response, client_id=client_id,
                        token_url=base + "/token", scope=scope)
            print(f"Microsoft authorization saved to macOS Keychain reference {ref!r}.")
            return
        if response.get("error") == "authorization_pending":
            continue
        if response.get("error") == "slow_down":
            interval += 5
            continue
        raise AuthRequired("Microsoft device code denied, expired, or not approved")
    raise AuthRequired("Microsoft device login timed out")
