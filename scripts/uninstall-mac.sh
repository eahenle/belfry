#!/bin/bash
# Removes agents and installed app; preserves config, snapshots and Keychain items.
set -euo pipefail
for label in dev.kernstein.notification-widget.collector dev.kernstein.notification-widget.panel; do
  plist="$HOME/Library/LaunchAgents/$label.plist"
  if [[ -f "$plist" ]]; then
    launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
    rm "$plist"
  fi
done
rm -rf "$HOME/Applications/Signals.app"
echo "Stopped/uninstalled Signals. Data and Keychain credentials have been preserved."
