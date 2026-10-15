#!/bin/bash
set -euo pipefail
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'This step requires macOS with Xcode Command Line Tools.' >&2; exit 1
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/build"
mkdir -p "$DEST/Signals.app/Contents/MacOS" "$DEST/bin"
cp "$ROOT/mac/Info.plist" "$DEST/Signals.app/Contents/Info.plist"
TARGET="$(uname -m)-apple-macosx14.0"
xcrun swiftc -O -swift-version 5 -target "$TARGET" -o "$DEST/Signals.app/Contents/MacOS/NotificationWidget" \
  "$ROOT/mac/Sources/NotificationWidget.swift" -framework AppKit -framework SwiftUI -framework Combine
xcrun swiftc -O -swift-version 5 -target "$TARGET" -o "$DEST/bin/widget-keychain" "$ROOT/mac/Helpers/Keychain.swift" -framework Security
xcrun swiftc -O -swift-version 5 -target "$TARGET" -o "$DEST/bin/dock-badge" "$ROOT/mac/Helpers/DockBadge.swift" \
  -framework AppKit -framework ApplicationServices
# Stable local unsigned development bundle; no external signing account needed.
codesign --force --sign - "$DEST/Signals.app"
echo "Built $DEST/Signals.app and macOS helpers in $DEST/bin"
