"""Atomic, mode-0600 snapshot files; never publish credentials."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .model import VERSION, utcnow


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            obj = json.load(fh)
        if obj.get("version") == VERSION and isinstance(obj.get("channels"), list):
            return obj
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {"version": VERSION, "generated_at": None, "channels": []}


def atomic_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        fd, name = tempfile.mkstemp(prefix=".snapshot-", suffix=".json", dir=path.parent)
        tmp_path = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"), indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def write_snapshot(path: Path, results: list[dict[str, Any]]) -> None:
    atomic_json(path, {"version": VERSION, "generated_at": utcnow(), "channels": results})
