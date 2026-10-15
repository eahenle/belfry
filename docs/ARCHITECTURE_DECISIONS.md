# ADR-001 · Native panel, file-backed scheduler, deterministic collectors

Date: 2026-10-14. Status: Accepted for MVP, subject to macOS smoke test.

## Decision

Use a SwiftUI-hosted nonactivating `NSPanel` with a `MenuBarExtra`; a Python 3.10+ coordinator started by per-user `launchd`; small deterministic providers with Keychain-backed secrets; and a versioned JSON snapshot written atomically. The panel watches the snapshot's **directory** rather than the replaced inode, with periodic fallback reads. Display and coordinator can be tested independently using simulated fixtures. No socket server, database, message broker, always-on model, cron or Docker dependency.

## Why not the proposed cron + Codex + Docker design?

A model can help build and debug adapters but is unnecessary and costly to fetch deterministic integer counts. Per-minute Codex execution adds latency, cost, account access surface, non-determinism, and potential context hallucination. Cron is less well integrated with macOS login lifecycle, sleep/wake and KeepAlive than user launch agents. Docker can be added later for non-native headless collectors, but it complicates access to macOS Keychain, AppKit, and the Dock.

## Why a panel instead of WidgetKit?

macOS WidgetKit update policy/timelines do not guarantee minute-level fresh application data; the spec needs per-provider refresh and stale/error badges. A borderless floating `NSPanel` permits steady visibility and UI control, while a menu bar item can hide it. A WidgetKit presentation could read the same snapshot in a later iteration but should not become the scheduler.

## Why Python coordinator instead of all Swift?

A lightweight, standard-library-only Python subprocess has broad access to HTTP, IMAP, test doubles and external adapters and is easy to expand without recompiling the native UI. The SwiftUI side is purely a view model over schema v1; the Security.framework and Dock Accessibility integrations remain native Swift helpers. Trade-off: macOS needs separate Python 3.10+ installation and launch agent coordination. Fully native Swift collector port remains an option if deployment becomes more important than adapter velocity.

## Why no generic combined total?

Counts represent messages, conversations, notification threads, approximate JQL-matching issues, or a badge. Adding different units is a measurement error. Each row declares account, scope and unit. Explicit aggregates could later be added only if they preserve compatible units and avoid overlap.

## Alternatives considered

- Browser DOM scraping and session-token extraction: rejected for security, brittleness and account/ToS risk.
- Community unofficial endpoints: rejected for unsupported/authenticity problems.
- Per-user Discord self-bot tokens: rejected, Discord forbids self-bots.
- Webex/Confluence synthetic counts from unrelated API fields: rejected as dishonest.
- Core Data/SQLite: unnecessary for a single latest snapshot. History may be useful later.
- Network daemon/webhooks: disproportionate for local desktop MVP; many webhook APIs require public endpoints.

## Open issues

- Native Swift build, Accessibility checks and visual test require a Mac running 14+.
- TCC may not expose numeric Dock badges for one or all selected apps; no zero can be assumed.
- Enterprise SSO/access restrictions depend on employer and specific accounts.
- Token-refresh and signed distribution should be tested with real OAuth clients. No notarized/notary-distributed binary is included.
