#!/bin/bash
# Installs under the current account, without sudo. Requires macOS 14+.
set -euo pipefail
if [[ "$(uname -s)" != "Darwin" ]]; then echo "Run on macOS" >&2; exit 1; fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v python3 >/dev/null; then echo "Install Python >=3.10 first" >&2; exit 1; fi
python3 - <<'PY'
import sys
if sys.version_info < (3,10): raise SystemExit('Python >= 3.10 required')
PY
"$ROOT/scripts/build-mac.sh"
APP_HOME="$HOME/Library/Application Support/NotificationWidget"
APP_BIN="$APP_HOME/bin"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/NotificationWidget"
APP_DEST="$HOME/Applications/Signals.app"
mkdir -p "$APP_HOME" "$APP_BIN" "$LAUNCH_AGENTS" "$LOG_DIR" "$HOME/Applications"
chmod 700 "$APP_HOME"
/usr/bin/ditto "$ROOT/build/Signals.app" "$APP_DEST"
/usr/bin/ditto "$ROOT/build/bin" "$APP_BIN"
# Standalone executable signed once at installed path, to support Accessibility TCC approvals.
codesign --force --sign - "$APP_BIN/dock-badge" "$APP_BIN/widget-keychain" >/dev/null
# Copy source, not user config/snapshots; upgrading code must not destroy account setup.
mkdir -p "$APP_HOME/project"
cp -R "$ROOT/notifydock" "$APP_HOME/project/"
cp -R "$ROOT/examples" "$APP_HOME/project/"
find "$APP_HOME/project" -name '__pycache__' -type d -prune -exec rm -rf {} +
PYTHON_EXEC="$(command -v python3)"
export APP_HOME APP_DEST LAUNCH_AGENTS LOG_DIR PYTHON_EXEC
PYTHONPATH="$APP_HOME/project" "$PYTHON_EXEC" -m notifydock.cli init
"$PYTHON_EXEC" - <<'PY'
import os, plistlib
from pathlib import Path
home=Path(os.environ['APP_HOME'])
launch=Path(os.environ['LAUNCH_AGENTS'])
log=Path(os.environ['LOG_DIR'])
python=os.environ['PYTHON_EXEC']
app=os.environ['APP_DEST']
services = {
    'dev.kernstein.notification-widget.collector': {
       'Label': 'dev.kernstein.notification-widget.collector',
       'ProgramArguments': [python, '-m', 'notifydock.cli', 'run'],
       'EnvironmentVariables': {'PYTHONPATH': str(home/'project')},
       'WorkingDirectory': str(home/'project'),
       'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 20,
       'StandardOutPath': str(log/'coordinator.log'), 'StandardErrorPath': str(log/'coordinator-error.log')},
    'dev.kernstein.notification-widget.panel': {
       'Label': 'dev.kernstein.notification-widget.panel',
       'ProgramArguments': ['/usr/bin/open', '-a', app],
       'RunAtLoad': True, 'KeepAlive': False}
}
for name, payload in services.items():
    with (launch/f'{name}.plist').open('wb') as f:
        plistlib.dump(payload, f)
PY
for label in dev.kernstein.notification-widget.collector dev.kernstein.notification-widget.panel; do
  plist="$LAUNCH_AGENTS/$label.plist"
  launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
done
# Start UI now rather than requiring a logout/login.
/usr/bin/open -a "$APP_DEST"
echo
printf 'Installed Signals: %s\nConfiguration: %s\nLogs: %s\n' "$APP_DEST" "$APP_HOME/config.json" "$LOG_DIR"
echo "All collectors start disabled. Connect your accounts, then enable channels."
