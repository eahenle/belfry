"""Concurrent per-channel collection, backoff, sleep/wake recovery and live reload."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import read_config
from .http import CollectorError
from .keychain import Keychain
from .model import ChannelConfig, Reading, failed_result, initial_result, successful_result
from .providers import collect
from .snapshot import load_snapshot, write_snapshot

LOG = logging.getLogger(__name__)


@dataclass
class Slot:
    config: ChannelConfig
    next_due: float = 0.0
    failures: int = 0
    min_refresh: int = 0
    last_started: float = -1e9
    rate_limit_until: float = 0.0
    future: Future | None = None


class Coordinator:
    def __init__(self, config_path: Path, snapshot_path: Path, refresh_path: Path,
                 *, collector: Callable[[ChannelConfig, Keychain], Reading] = collect,
                 keychain: Keychain | None = None, workers: int = 4,
                 clock: Callable[[], float] = time.monotonic):
        self.config_path = config_path
        self.snapshot_path = snapshot_path
        self.refresh_path = refresh_path
        self.collector = collector
        self.keychain = keychain or Keychain()
        self.clock = clock
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collector")
        self.slots: dict[str, Slot] = {}
        self.channels: list[ChannelConfig] = []
        self.results: dict[str, dict] = {}
        self._stop = threading.Event()
        self._config_mtime: int | None = None
        self._refresh_mtime: int | None = None
        self._last_wall: float = time.time()
        self._last_mono: float = self.clock()
        self.reload(force=True)

    def reload(self, force: bool = False) -> bool:
        try:
            mtime = self.config_path.stat().st_mtime_ns
        except OSError:
            LOG.error("Configuration not found; install or run init first")
            return False
        if not force and mtime == self._config_mtime:
            return False
        try:
            channels = read_config(self.config_path)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            LOG.error("Configuration invalid; retaining last known valid configuration: %s", type(exc).__name__)
            return False
        original = load_snapshot(self.snapshot_path)
        prior = {r["id"]: r for r in original["channels"] if isinstance(r, dict) and "id" in r}
        prior.update(self.results)
        new_slots: dict[str, Slot] = {}
        new_results: dict[str, dict] = {}
        for ch in channels:
            prev = self.slots.get(ch.id)
            slot = prev if prev and prev.config == ch else Slot(ch)
            if prev is not None and prev.config != ch and ch.enabled and prev.config.enabled:
                # A label/URL edit must not reset the provider's rate-limit floor.
                slot.next_due = prev.next_due
                slot.min_refresh = prev.min_refresh
                slot.last_started = prev.last_started
                slot.rate_limit_until = prev.rate_limit_until
            if prev is None and ch.id in prior and ch.enabled:
                old = prior[ch.id]
                slot.min_refresh = max(0, min(86400, int(old.get("min_refresh_seconds") or 0)))
                try:
                    checked = datetime.fromisoformat((old.get("checked_at") or "").replace("Z", "+00:00"))
                    age = time.time() - checked.timestamp()
                    slot.next_due = self.clock() + max(0, max(ch.refresh_seconds, slot.min_refresh) - age)
                except (ValueError, TypeError, OverflowError):
                    pass
            new_slots[ch.id] = slot
            if not ch.enabled:
                new_results[ch.id] = initial_result(ch)
            elif ch.id in prior:
                old = prior[ch.id]
                new_results[ch.id] = {**initial_result(ch),
                    "count": old.get("count"), "precision": old.get("precision", "unknown"),
                    "status": old.get("status", "unavailable"),
                    "detail": old.get("detail", "Not checked yet"),
                    "observed_at": old.get("observed_at"),
                    "checked_at": old.get("checked_at"),
                    "last_success_at": old.get("last_success_at"),
                    "min_refresh_seconds": old.get("min_refresh_seconds", 0)}
            else:
                new_results[ch.id] = initial_result(ch)
        self.slots, self.channels, self.results = new_slots, channels, new_results
        self._config_mtime = mtime
        self.publish()
        return True

    def publish(self) -> None:
        write_snapshot(self.snapshot_path, [self.results[ch.id] for ch in self.channels])

    def force_refresh(self) -> None:
        for slot in self.slots.values():
            # Respect provider poll headers and HTTP Retry-After even on manual refresh.
            if slot.config.enabled and not slot.future:
                earliest = max(self.clock(), slot.last_started + slot.min_refresh, slot.rate_limit_until)
                slot.next_due = earliest

    def check_refresh_request(self) -> None:
        try:
            mtime = self.refresh_path.stat().st_mtime_ns
        except OSError:
            return
        if mtime != self._refresh_mtime:
            self._refresh_mtime = mtime
            self.force_refresh()

    def _record_future(self, slot: Slot, now: float) -> None:
        ch = slot.config
        future = slot.future
        assert future is not None
        slot.future = None
        if ch.id not in self.results:
            return  # removed during in-flight request
        try:
            reading = future.result()
            if not isinstance(reading, Reading):
                raise ValueError("invalid collector result")
            if reading.count is None:
                self.results[ch.id] = failed_result(ch, self.results.get(ch.id),
                                                    "unavailable", reading.detail or "No count returned")
            else:
                self.results[ch.id] = successful_result(ch, reading, simulated=(ch.collector == "mock"))
            slot.min_refresh = max(slot.min_refresh, reading.min_refresh_seconds)
            slot.failures = 0
            slot.next_due = now + max(ch.refresh_seconds, slot.min_refresh)
        except Exception as exc:
            # Credential/server payload must never enter logs or snapshots.
            if isinstance(exc, CollectorError):
                status = exc.status
                retry_after = exc.retry_after
                detail = str(exc)
            else:
                status, retry_after, detail = "error", 0, "Collector execution failed"
            slot.failures += 1
            retry = min(3600, max(ch.refresh_seconds, slot.min_refresh) * (2 ** min(slot.failures, 6)))
            slot.rate_limit_until = now + retry_after if retry_after else 0.0
            slot.next_due = now + max(retry, retry_after)
            self.results[ch.id] = failed_result(ch, self.results.get(ch.id), status, detail)
            LOG.warning("Collector failed for %s (%s)", ch.id, status)
        self.publish()

    def tick(self) -> None:
        """One coordinator iteration, deterministic with injectable clock for tests."""
        now_wall = time.time()
        now_mono = self.clock()
        extra_wall = (now_wall - self._last_wall) - (now_mono - self._last_mono)
        if extra_wall > 30:
            # On macOS monotonic clocks may suspend while laptop sleeps. Translate
            # monotonic deadlines so a wake after hours does not wait hours again.
            for slot in self.slots.values():
                slot.last_started -= extra_wall
                slot.next_due -= extra_wall
                slot.rate_limit_until -= extra_wall
            LOG.info("Clock suspend/wake detected; scheduling overdue refreshes")
        self._last_wall, self._last_mono = now_wall, now_mono
        self.reload()
        self.check_refresh_request()
        now = self.clock()
        # Read completed futures before launching another round; an individual's
        # stalled network request cannot stop scheduling other providers.
        for slot in self.slots.values():
            if slot.future is not None and slot.future.done():
                self._record_future(slot, now)
        for slot in self.slots.values():
            if slot.config.enabled and slot.future is None and now >= slot.next_due:
                slot.last_started = now
                slot.future = self.pool.submit(self.collector, slot.config, self.keychain)

    def once(self, deadline_seconds: int = 90) -> None:
        self.tick()
        deadline = time.monotonic() + deadline_seconds
        while any(s.future is not None for s in self.slots.values()) and time.monotonic() < deadline:
            time.sleep(0.05)
            self.tick()
        if any(s.future is not None for s in self.slots.values()):
            LOG.warning("Some collectors exceeded one-shot deadline")

    def run(self, period: float = 1.0) -> None:
        try:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(period)
        finally:
            self.close()

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        # No unbounded shutdown hang when OS/network dependencies misbehave.
        self.pool.shutdown(wait=False, cancel_futures=True)
