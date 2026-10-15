#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHONPATH="$ROOT" python3 -m unittest discover -v -s tests
for file in mac/Sources/*.swift mac/Helpers/*.swift; do
    if command -v swiftc >/dev/null; then swiftc -frontend -parse "$file"; fi
done
python3 - <<'PY'
import plistlib
with open('mac/Info.plist','rb') as f: p=plistlib.load(f)
assert p['LSUIElement']
assert p['CFBundleExecutable'] == 'NotificationWidget'
print('Info.plist schema: OK')
PY
