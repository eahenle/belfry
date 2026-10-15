"""Versioned channel and snapshot contract. No credentials appear in snapshots."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Optional
from urllib.parse import urlparse

VERSION = 1
PRECISIONS = {"exact", "approximate", "lower_bound", "limited", "unknown"}
STATUSES = {"ok", "error", "auth_required", "unsupported", "unavailable", "disabled", "simulated"}
ALLOWED_METRICS = {
    "gmail": {"unread_messages", "unread_threads"},
    "github": {"unread_notification_threads"},
    "outlook": {"unread_mail_items"},
    "yahoo": {"unread_messages"},
    "jira": {"matching_jql_issues"},
    "slack": {"unread_dm_messages"},
    "dock_badge": {"application_badge"},
    "external": {"unread_messages", "unread_threads", "unread_notification_threads",
                 "unread_mail_items", "matching_jql_issues", "unread_dm_messages",
                 "application_badge", "other"},
    "unsupported": {"other", "application_badge", "unread_notifications"},
    "mock": {"unread_messages", "unread_threads", "unread_notification_threads",
             "unread_mail_items", "matching_jql_issues", "unread_dm_messages", "application_badge", "other"},
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def valid_url(value: str) -> bool:
    """Only known-safe click targets. No javascript:, file:, or embedded passwords."""
    try:
        p = urlparse(value)
    except ValueError:
        return False
    return bool(p.scheme == "https" and p.hostname and not p.username and not p.password)


@dataclass(frozen=True)
class ChannelConfig:
    provider: str
    account: str
    scope: str
    metric: str
    display_name: str
    collector: str
    refresh_seconds: int = 120
    enabled: bool = False
    url: str = ""
    secret_ref: str = ""
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Stable opaque ID determined only by provider/account/scope/metric."""
        raw = "\x1f".join((self.provider, self.account, self.scope, self.metric))
        return "ch_" + sha256(raw.encode()).hexdigest()[:24]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChannelConfig":
        if not isinstance(data, dict):
            raise ValueError("channel must be an object")
        settings = data.get("settings", {})
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        ch = cls(
            provider=data["provider"], account=data["account"], scope=data["scope"],
            metric=data["metric"], display_name=data["display_name"],
            collector=data.get("collector", data["provider"]),
            refresh_seconds=data.get("refresh_seconds", 120),
            enabled=data.get("enabled", False), url=data.get("url", ""),
            secret_ref=data.get("secret_ref", ""), settings=settings,
        )
        for name in ("provider", "account", "scope", "metric", "display_name", "collector"):
            if not isinstance(getattr(ch, name), str) or not getattr(ch, name).strip():
                raise ValueError(f"{name} must be a nonempty string")
            if "\x1f" in getattr(ch, name) or any(ord(c) < 32 for c in getattr(ch, name)):
                raise ValueError(f"{name} contains control characters")
        if not isinstance(ch.enabled, bool):
            raise ValueError("enabled must be boolean")
        if type(ch.refresh_seconds) is not int or not 30 <= ch.refresh_seconds <= 86400:
            raise ValueError("refresh_seconds must be between 30 and 86400")
        if ch.collector not in ALLOWED_METRICS:
            raise ValueError(f"unknown collector: {ch.collector}")
        if ch.metric not in ALLOWED_METRICS[ch.collector]:
            raise ValueError(f"metric {ch.metric!r} unsupported by {ch.collector!r}")
        if not isinstance(ch.url, str) or (ch.url and not valid_url(ch.url)):
            raise ValueError("click-through URL must be https without embedded credentials")
        if not isinstance(ch.secret_ref, str):
            raise ValueError("secret_ref must be string")
        if ch.collector == "dock_badge" and (not isinstance(settings.get("app_name"), str) or not settings["app_name"]):
            raise ValueError("dock_badge requires settings.app_name")
        if ch.collector == "slack" and (not isinstance(settings.get("channel_id"), str) or not settings["channel_id"]):
            raise ValueError("slack DM requires settings.channel_id")
        if ch.collector == "jira" and (not isinstance(settings.get("jql"), str) or not settings["jql"]):
            raise ValueError("jira requires settings.jql")
        if ch.collector == "external":
            cmd = settings.get("command")
            if not (isinstance(cmd, list) and len(cmd) >= 1 and all(isinstance(s, str) and s for s in cmd)):
                raise ValueError("external requires nonempty settings.command list")
            if not cmd[0].startswith("/"):
                raise ValueError("external executable path must be absolute")
        if ch.collector == "unsupported" and ch.enabled:
            raise ValueError("unsupported collector cannot be enabled")
        return ch

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "provider": self.provider, "account": self.account,
                "scope": self.scope, "metric": self.metric, "display_name": self.display_name,
                "refresh_seconds": self.refresh_seconds, "enabled": self.enabled,
                "url": self.url}


@dataclass(frozen=True)
class Reading:
    count: Optional[int]
    precision: str = "exact"
    detail: str = ""
    min_refresh_seconds: int = 0

    def __post_init__(self) -> None:
        if self.count is not None and (type(self.count) is not int or self.count < 0):
            raise ValueError("count must be a nonnegative integer or null")
        if self.precision not in PRECISIONS:
            raise ValueError("invalid precision")
        if type(self.min_refresh_seconds) is not int or self.min_refresh_seconds < 0:
            raise ValueError("invalid minimum refresh interval")
        if self.count is None and self.precision == "exact":
            raise ValueError("null count cannot be exact")
        if len(self.detail) > 400:
            raise ValueError("detail too long")


def initial_result(ch: ChannelConfig) -> dict[str, Any]:
    return {
        **ch.public(), "count": None, "precision": "unknown", "status": "unsupported" if ch.collector == "unsupported" else ("disabled" if not ch.enabled else "unavailable"),
        "detail": "No supported count API or reliable local fallback" if ch.collector == "unsupported" else ("Disabled in configuration" if not ch.enabled else "Not checked yet"),
        "observed_at": None, "checked_at": None, "last_success_at": None, "min_refresh_seconds": 0,
    }


def successful_result(ch: ChannelConfig, reading: Reading, now: str | None = None,
                      simulated: bool = False) -> dict[str, Any]:
    now = now or utcnow()
    return {
        **ch.public(), "count": reading.count, "precision": reading.precision,
        "status": "simulated" if simulated else ("ok" if reading.count is not None else "unavailable"),
        "detail": reading.detail, "observed_at": now if reading.count is not None else None,
        "checked_at": now, "last_success_at": now if reading.count is not None else None,
        "min_refresh_seconds": reading.min_refresh_seconds,
    }


def failed_result(ch: ChannelConfig, previous: dict[str, Any] | None,
                  status: str, detail: str, now: str | None = None) -> dict[str, Any]:
    if status not in {"error", "auth_required", "unavailable", "unsupported"}:
        raise ValueError("invalid failure status")
    old = previous or {}
    return {
        **ch.public(), "count": old.get("count"),
        "precision": old.get("precision", "unknown"), "status": status,
        "detail": detail[:400], "observed_at": old.get("observed_at"),
        "checked_at": now or utcnow(), "last_success_at": old.get("last_success_at"),
        "min_refresh_seconds": old.get("min_refresh_seconds", 0),
    }
