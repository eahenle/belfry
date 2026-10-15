"""CLI for setup, configuration, authentication, coordinator and demo."""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__
from .config import CONFIG_PATH, DATA_HOME, REFRESH_PATH, SNAPSHOT_PATH, initialize, read_config
from .coordinator import Coordinator
from .http import CollectorError
from .keychain import Keychain, SecretUnavailable
from .model import ChannelConfig, initial_result, successful_result, Reading
from .snapshot import atomic_json, load_snapshot, write_snapshot


def example_file() -> Path:
    # App Support/install path contains examples when installed via install.sh.
    return Path(__file__).resolve().parent.parent / "examples" / "config.example.json"


def config_edit(path: Path, mutate) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc["channels"])
    if doc.get("version") != 1:
        raise ValueError("Unsupported config version")
    channels = [ChannelConfig.from_dict(c) for c in doc["channels"]]
    if len({c.id for c in channels}) != len(channels):
        raise ValueError("Duplicate channel identity")
    atomic_json(path, doc)


def find_entry(items: list[dict], id_or_index: str) -> int:
    if id_or_index.isdigit() and 0 <= int(id_or_index) < len(items):
        return int(id_or_index)
    for i, item in enumerate(items):
        if ChannelConfig.from_dict(item).id == id_or_index:
            return i
    raise ValueError("No channel with this index/ID")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Notification Widget macOS coordinator")
    p.add_argument("--config", type=Path, default=CONFIG_PATH)
    p.add_argument("--snapshot", type=Path, default=SNAPSHOT_PATH)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize local channel configuration")
    run = sub.add_parser("run", help="Run collectors under launchd")
    run.add_argument("--once", action="store_true")
    sub.add_parser("status", help="Show most recent results, never secrets")
    sub.add_parser("refresh", help="Request prompt refresh from running service")
    sub.add_parser("demo", help="Write explicitly simulated panel data")
    secret = sub.add_parser("secret", help="Manage native macOS Keychain credentials")
    secret.add_argument("action", choices=["set", "delete"])
    secret.add_argument("ref")
    auth = sub.add_parser("auth", help="Complete supported read-only OAuth flows")
    auth.add_argument("provider", choices=["google", "microsoft"])
    auth.add_argument("--ref", required=True)
    auth.add_argument("--client-json", type=Path)
    auth.add_argument("--client-id")
    auth.add_argument("--tenant", default="common")
    channel = sub.add_parser("channel", help="Manage channel config without manual JSON editing")
    channel.add_argument("action", choices=["list", "enable", "disable", "move", "remove", "add"])
    channel.add_argument("identity", nargs="?")
    channel.add_argument("position", nargs="?", type=int)
    channel.add_argument("--file", type=Path, help="JSON channel object for add")
    args = p.parse_args(argv)
    path = args.config
    snapshot = args.snapshot
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    if args.command == "init":
        created = initialize(path, example_file())
        if created:
            write_snapshot(snapshot, [initial_result(ch) for ch in read_config(path)])
        print(("Initialized" if created else "Already present") + f": {path}")
        return 0
    if args.command == "secret":
        kc = Keychain()
        if args.action == "set":
            value = getpass.getpass(f"Credential for {args.ref} (hidden): ")
            kc.set(args.ref, value)
            print("Stored in macOS Keychain")
        else:
            kc.delete(args.ref)
            print("Keychain credential deleted")
        return 0
    if args.command == "auth":
        from .auth import google_login, microsoft_login
        kc = Keychain()
        if args.provider == "google":
            if not args.client_json:
                p.error("Google auth requires --client-json /path/to/desktop-oauth.json")
            google_login(kc, args.ref, args.client_json)
        else:
            if not args.client_id:
                p.error("Microsoft auth requires --client-id APP_ID")
            microsoft_login(kc, args.ref, args.client_id, args.tenant)
        return 0
    if args.command == "status":
        data = load_snapshot(snapshot)
        for row in data["channels"]:
            print(f"{row.get('display_name','?'):<24} {str(row.get('count')):<8} "
                  f"{row.get('metric','?'):<28} {row.get('status','?'):<15} "
                  f"{row.get('precision','?')}")
        return 0
    if args.command == "channel":
        if args.action == "list":
            for i, c in enumerate(read_config(path)):
                print(f"{i:2}  {'ON ' if c.enabled else 'OFF'}  {c.display_name:22} "
                      f"{c.collector:12} {c.metric:28} {c.id}")
            return 0
        def change(items):
            if args.action == "add":
                if not args.file:
                    p.error("channel add requires --file /path/to/new-channel.json")
                item = json.loads(args.file.read_text(encoding="utf-8"))
                ChannelConfig.from_dict(item)
                items.append(item)
            else:
                if args.identity is None:
                    p.error("Specify channel index or stable ID")
                index = find_entry(items, args.identity)
                if args.action in ("enable", "disable"):
                    items[index]["enabled"] = args.action == "enable"
                elif args.action == "remove":
                    items.pop(index)
                elif args.action == "move":
                    if args.position is None or not 0 <= args.position < len(items):
                        p.error("channel move requires valid destination index")
                    item = items.pop(index)
                    items.insert(args.position, item)
        config_edit(path, change)
        print("Configuration saved; coordinator reloads automatically")
        return 0
    if args.command == "refresh":
        refresh_path = path.parent / "refresh.request"
        refresh_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_path.write_text(str(time.time_ns()), encoding="ascii")
        return 0
    if args.command == "demo":
        if not path.exists():
            initialize(path, example_file())
        samples = [4, 7, 12, 3, 2, 9, 1, 5, 14, 6, 8]
        channels = read_config(path)
        output = []
        for i, ch in enumerate(channels):
            if ch.collector == "unsupported":
                output.append(initial_result(ch))
                continue
            row = successful_result(ch, Reading(samples[i % len(samples)],
                           "approximate" if ch.collector == "jira" else ("limited" if ch.collector == "dock_badge" else "exact"),
                           "SIMULATED preview, not a real account"), simulated=True)
            output.append(row)
        write_snapshot(snapshot, output)
        print(f"SIMULATED preview written to {snapshot}. No messages were accessed.")
        return 0
    if args.command == "run":
        if not path.exists():
            print("No configuration. Run 'notification-widget init' first", file=sys.stderr)
            return 2
        coordinator = Coordinator(path, snapshot, path.parent / "refresh.request")
        if args.once:
            coordinator.once()
            coordinator.close()
            return 0
        try:
            coordinator.run()
        except KeyboardInterrupt:
            coordinator.stop()
            coordinator.close()
        return 0
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, SecretUnavailable, CollectorError) as exc:
        # Never print credential-bearing exceptions.
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
