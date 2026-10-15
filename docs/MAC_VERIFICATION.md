# macOS build & verification checklist

**Not completed in Linux source environment.** Do all on a Mac running macOS 14+ with Xcode Command Line Tools:

- [ ] Run `./scripts/test.sh`: unit tests, Swift source parse, Info.plist validation.
- [ ] Run `./scripts/build-mac.sh`: SwiftUI/AppKit app + both native helpers compile, link and ad-hoc sign.
- [ ] Run `./scripts/install-mac.sh` and verify `~/Applications/Signals.app` opens.
- [ ] Check menu bar icon; show/hide panel and `Show in All Spaces` behavior.
- [ ] Inspect light and dark mode, focus behavior, background visibility, panel dragging/position persistence and correct ordered channel labels.
- [ ] Run `python3 -m notifydock.cli demo`; verify **demo** indicators and precise metric labeling, not live counts.
- [ ] Enable GitHub and Gmail (or another two separate real collectors) only after authorizing them. Confirm actual counts in each provider's UI within a reasonable delay. Do not consider two mock counts milestone-complete.
- [ ] Verify click-through for each configured provider with a suitable account-specific `https://` URL.
- [ ] Disable network; verify earlier count remains but displays error/stale, not zero.
- [ ] Revoke or temporarily delete a Keychain token; verify `auth_required` and previous successful reading.
- [ ] Put laptop to sleep, then wake; verify coordinator refreshes due sources and snapshot timestamp updates.
- [ ] Grant Accessibility to Dock observer, inspect a running app with and without badge. Confirm correct detection if available, or honest unavailable status if not.
- [ ] Close and reopen app, logout/login, and check user launch agents `launchctl print gui/$(id -u)/dev.kernstein.notification-widget.collector`.
- [ ] Test multiple accounts of same provider and `channel move` order updates without rebuilding SwiftUI.
- [ ] Audit network traffic: only official read-oriented provider hosts/auth, no telemetry, and no messages marked read by polling.

A passing checklist would justify moving specific rows from **fixture-tested** to **macOS-verified/live-tested** in `docs/CAPABILITY_MATRIX.md`.
