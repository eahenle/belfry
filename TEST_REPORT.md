# Test report · 2026-10-14 (US Pacific)

**Environment:** Linux x86_64, Python 3.13.5, Swift 6.2.1 parser. macOS AppKit and SwiftUI frameworks unavailable in this build environment.

**Command:** `./scripts/test.sh`

**Result:** 36 automated Python unit/integration-fixture tests passed. Swift files parsed successfully (`swiftc -frontend -parse`, separate per file). macOS `Info.plist` loaded and validated. Python source compiled via `compileall`.

**Simulated smoke test:** With an isolated config initialized and GitHub enabled but no stored credential, a one-shot coordinator run yielded `auth_required` and `count: null`, not zero; other channels remained disabled/unsupported and the snapshot contained no `secret_ref`. This demonstrates graceful failure but not a live provider connection.

**Coverage:** Config/model/identities, distinct metrics, JSON atomic write permissions, multiple accounts, stale count preservation, authentication failure, partial failures, server poll headers, retry-after/backoff, sleep/wake, restarts, config reload, read-only Gmail/Outlook/GitHub/Yahoo/Slack/Jira adapter behavior, external subprocess contract, Dock adapter fixture, OAuth refresh, redirect credential isolation, pagination cap lower bounds.

**Not tested:** Building/running native macOS application, Dock Accessibility runtime, actual Google/Microsoft/Slack/GitHub/Yahoo/Jira accounts, app signing/notarization, full sleep/wake on hardware, enterprise tenant policies. All require macOS or user-controlled auth. Do not label first live-two-source milestone complete until verification checklist has passed.

**Next verification on Mac:** `./scripts/test.sh && ./scripts/build-mac.sh && ./scripts/install-mac.sh`, connect at least two real accounts, validate their counts against native provider UI, and complete `docs/MAC_VERIFICATION.md`.
