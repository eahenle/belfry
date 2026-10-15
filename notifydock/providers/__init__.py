"""Provider adapters. All adapters are read-only with respect to user's message state."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

from ..config import DATA_HOME
from ..http import AuthRequired, CollectorError, Unavailable, Unsupported
from ..keychain import Keychain, SecretUnavailable
from ..model import ChannelConfig, Reading


def secret(keychain: Keychain, ch: ChannelConfig) -> str:
    if not ch.secret_ref:
        raise AuthRequired("Configure a Keychain secret_ref first")
    try:
        return keychain.get(ch.secret_ref)
    except SecretUnavailable as exc:
        raise AuthRequired(str(exc)) from None


def oauth_secret(keychain: Keychain, ch: ChannelConfig) -> str:
    if not ch.secret_ref:
        raise AuthRequired("Configure an OAuth secret_ref first")
    from ..oauth import access_token
    return access_token(keychain, ch.secret_ref)


def github(ch: ChannelConfig, keychain: Keychain) -> Reading:
    from ..http import parse_next_link, request_json
    token = secret(keychain, ch)
    base_url = ch.settings.get("api_base", "https://api.github.com")
    if base_url != "https://api.github.com":
        raise Unsupported("Only GitHub.com is supported in this release")
    url = "https://api.github.com/notifications?per_page=100&all=false"
    total = 0
    minimum = 60
    max_pages = 20
    for page in range(max_pages):
        response, headers = request_json(url, {"Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28", "Accept": "application/vnd.github+json"})
        if not isinstance(response, list):
            raise CollectorError("GitHub notification response was not a list")
        total += len(response)
        for name, val in headers.items():
            if name.lower() == "x-poll-interval":
                try:
                    minimum = max(minimum, min(int(val), 86400))
                except ValueError:
                    pass
        link = next((v for k, v in headers.items() if k.lower() == "link"), "")
        url = parse_next_link(link, "https://api.github.com/notifications?")
        if not url:
            return Reading(total, "exact", "Unread notification threads", minimum)
    return Reading(total, "lower_bound", f"At least {total} unread threads; pagination safety cap reached", minimum)


def gmail(ch: ChannelConfig, keychain: Keychain) -> Reading:
    from ..http import request_json, require_int
    from urllib.parse import quote
    access = oauth_secret(keychain, ch)
    label = quote(ch.scope, safe="")
    obj, _ = request_json(f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{label}?fields=messagesUnread,threadsUnread",
                          {"Authorization": f"Bearer {access}"})
    field = "messagesUnread" if ch.metric == "unread_messages" else "threadsUnread"
    return Reading(require_int(obj.get(field), field), "exact", f"Unread {ch.metric.replace('_', ' ')} in label {ch.scope}")


def outlook(ch: ChannelConfig, keychain: Keychain) -> Reading:
    from ..http import request_json, require_int
    from urllib.parse import quote
    access = oauth_secret(keychain, ch)
    folder = quote(ch.scope, safe="")
    obj, _ = request_json(f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}?$select=unreadItemCount",
                          {"Authorization": f"Bearer {access}"})
    return Reading(require_int(obj.get("unreadItemCount"), "unreadItemCount"), "exact", f"Unread mail items in {ch.scope}")


def yahoo(ch: ChannelConfig, keychain: Keychain) -> Reading:
    import imaplib
    import re
    password = secret(keychain, ch)
    client = None
    try:
        client = imaplib.IMAP4_SSL("export.imap.mail.yahoo.com", 993, timeout=16)
        client.login(ch.account, password)
        # STATUS does not fetch messages and cannot change read state.
        status, data = client.status(ch.scope, "(UNSEEN)")
        if status != "OK" or not data:
            raise CollectorError("Yahoo IMAP STATUS returned no unread count")
        match = re.search(rb"\bUNSEEN\s+(\d+)\b", data[0])
        if not match:
            raise CollectorError("Yahoo IMAP returned an invalid UNSEEN response")
        return Reading(int(match.group(1)), "exact", f"Unread IMAP messages in {ch.scope}")
    except imaplib.IMAP4.error as exc:
        # IMAP auth errors can also be server policy errors. Do not echo server data.
        raise AuthRequired("Yahoo IMAP authentication or mailbox access failed") from None
    except (OSError, TimeoutError):
        raise CollectorError("Yahoo IMAP unavailable or timed out") from None
    finally:
        if client is not None:
            try:
                client.logout()
            except (OSError, imaplib.IMAP4.error):
                pass


def jira(ch: ChannelConfig, keychain: Keychain) -> Reading:
    import base64
    from ..http import request_json, require_int
    from urllib.parse import urlparse
    site = ch.settings.get("site", "")
    if not isinstance(site, str) or not site.startswith("https://") or urlparse(site).hostname is None or urlparse(site).username:
        raise Unsupported("Jira requires an https settings.site URL")
    # Support Atlassian Cloud only; prevent sending credentials to arbitrary domains.
    p = urlparse(site)
    if not p.hostname.endswith(".atlassian.net") or p.port not in (None, 443) or p.path.strip("/"):
        raise Unsupported("Jira API token collector supports only *.atlassian.net sites")
    token = secret(keychain, ch)
    basic = base64.b64encode(f"{ch.account}:{token}".encode()).decode("ascii")
    obj, _ = request_json(f"{site.rstrip('/')}/rest/api/3/search/approximate-count",
                          {"Authorization": f"Basic {basic}"},
                          {"jql": ch.settings["jql"]})
    return Reading(require_int(obj.get("count"), "count"), "approximate",
                   f"Approximate count matching JQL: {ch.settings['jql'][:230]}")


def slack(ch: ChannelConfig, keychain: Keychain) -> Reading:
    from ..http import request_json, require_int
    from urllib.parse import urlencode
    token = secret(keychain, ch)
    url = "https://slack.com/api/conversations.info?" + urlencode({"channel": ch.settings["channel_id"]})
    obj, _ = request_json(url, {"Authorization": f"Bearer {token}"})
    if not obj.get("ok"):
        err = obj.get("error", "")
        if err in ("not_authed", "invalid_auth", "missing_scope", "token_revoked", "token_expired"):
            raise AuthRequired("Slack DM token invalid or missing im:read scope")
        raise Unavailable("Slack cannot access this DM")
    convo = obj.get("channel", {})
    if not convo.get("is_im"):
        raise Unsupported("Slack public API does not expose unread counts for arbitrary channels")
    if "unread_count_display" not in convo:
        raise Unsupported("Slack did not return a per-user DM unread count for this token")
    return Reading(require_int(convo["unread_count_display"], "unread_count_display"), "exact",
                   f"Displayed unread DM messages in {ch.settings['channel_id']}")


def dock_badge(ch: ChannelConfig, keychain: Keychain) -> Reading:
    helper = Path(ch.settings.get("helper", DATA_HOME / "bin" / "dock-badge"))
    if not helper.is_file():
        raise Unavailable("macOS Dock badge observer not installed")
    try:
        completed = subprocess.run([str(helper), ch.settings["app_name"]],
                                  capture_output=True, text=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Unavailable("Dock badge inspection timed out") from None
    if completed.returncode != 0:
        raise Unavailable("Dock Accessibility access or application is unavailable")
    try:
        value = json.loads(completed.stdout)
    except (ValueError, UnicodeError):
        raise CollectorError("Dock observer returned invalid JSON") from None
    if value.get("state") == "permission_required":
        raise Unavailable("Allow Accessibility permission for the Dock observer")
    if value.get("state") == "not_found":
        raise Unavailable("Application icon not found in Dock")
    if value.get("state") == "no_badge":
        if ch.settings.get("no_badge_is_zero") is True:
            return Reading(0, "limited", "No visible badge; may mean zero or badges disabled")
        raise Unavailable("No numeric Dock badge; this does not establish zero")
    if value.get("state") != "numeric_badge":
        raise Unavailable("Dock badge not numerical or unavailable")
    count = value.get("count")
    if type(count) is not int or count < 0:
        raise CollectorError("Dock observer returned invalid badge count")
    return Reading(count, "limited", "Observed Dock app badge, not a guaranteed unread-message count")


def external(ch: ChannelConfig, keychain: Keychain) -> Reading:
    cmd = ch.settings["command"]
    timeout = min(max(1, int(ch.settings.get("timeout_seconds", 12))), 30)
    input_data = json.dumps({"version": 1, "channel": ch.public()}, separators=(",", ":"))
    try:
        completed = subprocess.run(cmd, input=input_data, capture_output=True,
                                  text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise CollectorError("External collector failed or timed out") from None
    if completed.returncode:
        raise CollectorError("External collector exited unsuccessfully")
    if len(completed.stdout) > 65536:
        raise CollectorError("External collector output too large")
    try:
        obj = json.loads(completed.stdout)
    except ValueError:
        raise CollectorError("External collector output was not JSON") from None
    if not isinstance(obj, dict) or obj.get("version") != 1:
        raise CollectorError("External collector JSON version mismatch")
    return Reading(obj.get("count"), obj.get("precision", "unknown"), obj.get("detail", ""))


def unsupported(ch: ChannelConfig, keychain: Keychain) -> Reading:
    raise Unsupported("No supported unread-count collector for this provider")


COLLECTORS: dict[str, Callable[[ChannelConfig, Keychain], Reading]] = {
    "github": github, "gmail": gmail, "outlook": outlook, "yahoo": yahoo,
    "jira": jira, "slack": slack, "dock_badge": dock_badge,
    "external": external, "unsupported": unsupported,
}


def collect(ch: ChannelConfig, keychain: Keychain) -> Reading:
    if ch.collector == "mock":
        return Reading(ch.settings.get("count", 0), "exact", "SIMULATED / NOT LIVE")
    return COLLECTORS[ch.collector](ch, keychain)
