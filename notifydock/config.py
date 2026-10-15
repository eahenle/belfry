"""Live-reloadable JSON config with strict schema and duplicate channel protection."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .model import ChannelConfig, VERSION

DATA_HOME = Path(os.environ.get("NOTIFICATION_WIDGET_HOME", Path.home() / "Library" / "Application Support" / "NotificationWidget"))
CONFIG_PATH = DATA_HOME / "config.json"
SNAPSHOT_PATH = DATA_HOME / "snapshot.json"
REFRESH_PATH = DATA_HOME / "refresh.request"


def read_config(path: Path = CONFIG_PATH) -> list[ChannelConfig]:
    with open(path, encoding="utf-8") as f:
        document = json.load(f)
    if not isinstance(document, dict) or document.get("version") != VERSION:
        raise ValueError(f"config requires version {VERSION}")
    items = document.get("channels")
    if not isinstance(items, list):
        raise ValueError("channels must be an array")
    channels = [ChannelConfig.from_dict(item) for item in items]
    ids = [c.id for c in channels]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate provider/account/scope/metric identity")
    return channels


def initialize(path: Path, example: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    shutil.copyfile(example, path)
    os.chmod(path, 0o600)
    read_config(path)
    return True
