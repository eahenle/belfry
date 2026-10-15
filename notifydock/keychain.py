"""A small, secret-safe bridge to the native macOS Security.framework helper.

Secrets travel over stdin/stdout only, never command-line arguments. The helper is
compiled by scripts/build-mac.sh and copied next to the installed coordinator.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import DATA_HOME


class SecretUnavailable(RuntimeError):
    pass


class Keychain:
    def __init__(self, helper: Path | None = None):
        self.helper = helper or Path(os.environ.get("NOTIFICATION_WIDGET_KEYCHAIN", DATA_HOME / "bin" / "widget-keychain"))

    def _run(self, action: str, ref: str, secret: str | None = None) -> str:
        if not ref or len(ref) > 200 or any(c in ref for c in "\r\n\x00"):
            raise ValueError("invalid secret reference")
        if not self.helper.is_file():
            raise SecretUnavailable("macOS Keychain helper not installed")
        try:
            result = subprocess.run([str(self.helper), action, ref], input=secret,
                                    capture_output=True, text=True, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SecretUnavailable("Keychain unavailable") from exc
        if result.returncode != 0:
            raise SecretUnavailable("Credential missing, inaccessible or Keychain locked")
        return result.stdout.rstrip("\n")

    def get(self, ref: str) -> str:
        return self._run("get", ref)

    def set(self, ref: str, secret: str) -> None:
        if not secret:
            raise ValueError("cannot store empty credential")
        self._run("set", ref, secret)

    def delete(self, ref: str) -> None:
        self._run("delete", ref)
