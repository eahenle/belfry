# Versioned collector contract (v1)

## Channel identity

Logical identity is `(provider, account, scope, metric)`. The coordinator hashes these four fields (length-prefixed by an unambiguous separator) into `ch_` plus 24 hex characters. Different accounts and different scopes are separate rows even on the same provider. Renaming the row does not reset its identity.

An example config channel:

```json
{
  "provider": "github",
  "account": "personal",
  "scope": "all unread notification threads",
  "metric": "unread_notification_threads",
  "display_name": "GitHub",
  "collector": "github",
  "enabled": true,
  "refresh_seconds": 120,
  "secret_ref": "github:personal",
  "url": "https://github.com/notifications"
}
```

`secret_ref` names a credential in macOS Keychain; it is **not** a token. The coordinator uses it only inside the trusted collector process. Channel JSON is stored mode 0600 by default.

## Snapshot v1 (one object per configured channel)

```json
{
  "version": 1,
  "generated_at": "2026-10-14T20:00:00Z",
  "channels": [
    {
      "id": "ch_<sha256 prefix>",
      "provider": "github",
      "account": "personal",
      "scope": "all unread notification threads",
      "metric": "unread_notification_threads",
      "display_name": "GitHub",
      "refresh_seconds": 120,
      "enabled": true,
      "url": "https://github.com/notifications",
      "count": 12,
      "precision": "exact",
      "status": "ok",
      "detail": "Unread notification threads",
      "observed_at": "2026-10-14T20:00:00Z",
      "checked_at": "2026-10-14T20:00:00Z",
      "last_success_at": "2026-10-14T20:00:00Z"
    }
  ]
}
```

Values for `count`: nonnegative integer including zero, or `null`. Never reinterpret `null` as zero. Precision: `exact`, `approximate`, `lower_bound`, `limited`, `unknown`. Status: `ok`, `error`, `auth_required`, `unsupported`, `unavailable`, `disabled`, `simulated`. `observed_at` and `last_success_at` stay unchanged after collection failure; `checked_at` changes on each attempt. `detail` is user-facing, capped at 400 characters. `url` is strictly `https:` with no embedded credentials.

A stale reading is computed from the age of `observed_at` in the macOS view (`max(300s, 2*refresh_seconds)`), or is displayed in an error state with a retained count. Snapshot files are mode 0600, written via temporary file + fsync + rename. Credentials and collector `settings` are omitted from the public snapshot.

## External collector executable

Configure:

```json
{
  "provider": "example-service",
  "account": "primary",
  "scope": "all-notifications",
  "metric": "unread_notification_threads",
  "display_name": "Example service",
  "collector": "external",
  "enabled": true,
  "refresh_seconds": 180,
  "url": "https://service.example/inbox",
  "settings": {"command": ["/absolute/path/to/collector", "--read-only"], "timeout_seconds": 12}
}
```

The coordinator calls the executable with a JSON object on stdin, for example:

```json
{
  "version": 1,
  "channel": {
    "id": "ch_...",
    "provider": "example-service",
    "account": "primary",
    "scope": "all-notifications",
    "metric": "unread_notification_threads",
    "display_name": "Example service",
    "refresh_seconds": 180,
    "enabled": true,
    "url": "https://service.example/inbox"
  }
}
```

The executable prints one JSON object to stdout (stderr ignored), e.g.:

```json
{"version": 1, "count": 8, "precision": "exact", "detail": "Eight unread threads"}
```

- Stdout must be valid JSON <=64 KB. Exit code 0 indicates a valid response; malformed output/timeouts become `error`.
- The executable **cannot** override channel identity, account, scope, metric, URL or health status. The coordinator owns those fields.
- No secret is sent to external collectors by default. If an external collector needs credentials, it must be an explicitly trusted local executable and access its own authorized credential store; no browser-token scraping.
- External binaries run with the privileges of the user, so review their code. This is an extensibility interface, not a sandbox. The current coordinator supports known type metrics but not arbitrarily invented names in the protocol.
- This protocol is stable to add a platform without touching the SwiftUI display. Example: [`examples/external_sample.py`](../examples/external_sample.py).

## Provider modules

The built-in interface is `collect(ChannelConfig, Keychain) -> Reading(count, precision, detail, min_refresh_seconds)`. A provider should:

1. Use the smallest official read-only API permission.
2. Declare exact semantics in its configured `metric` and `scope`. Never use an unrelated number.
3. Enforce timeouts. Handle pagination without pretending an incomplete page is exact.
4. Return `Reading(None, "unknown")` if data truly unavailable; coordinator preserves prior good count.
5. Raise `AuthRequired`, `Unavailable`, `Unsupported` or `CollectorError` with a non-secret-safe message.
6. Add fixture tests proving it does not change read state.

To extend a built-in collector, register it in `notifydock/providers/__init__.py`, define supported metrics in `model.ALLOWED_METRICS`, document auth/rate limitations, and add tests. External collectors require none of these source changes.
