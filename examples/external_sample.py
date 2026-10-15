#!/usr/bin/env python3
"""External collector v1 sample; replace placeholder logic with approved official API."""
import json
import sys

payload = json.load(sys.stdin)
if payload.get('version') != 1:
    sys.exit(2)
# No credentials are provided in payload. This is explicitly a sample, not live data.
print(json.dumps({'version': 1, 'count': None,
                  'precision': 'unknown', 'detail': 'Sample only; no provider connected'}))
