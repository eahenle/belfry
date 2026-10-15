# Belfry

**Signals** is Belfry’s macOS notification panel.

**Native macOS panel + read-only notification counter service.** One row per provider/account/scope/metric, no misleading grand total. The widget shows the latest count, freshness, scope, and authentication/collector health without opening ten apps.

**Target:** macOS 14+ · Python 3.10+ · SwiftUI + AppKit

> **Delivery status:** Code and automated fixtures are included. The source was developed/tested on Linux and **has not been compiled or run on a Mac**. Provider integrations are implemented and tested against mock responses, not authenticated live accounts. To display real counts, compile on macOS and connect at least two accounts. See [verified status matrix](docs/CAPABILITY_MATRIX.md).

## What is here

- **Signals.app**: a small SwiftUI/AppKit **nonactivating floating panel** with a menu bar icon, drag-to-position, saved position, all-Spaces option, light/dark appearance, ordered scrollable rows and click-through links. Native menu offers refresh and config editing. Sources and status are read from a local JSON file. No web server.
- **Coordinator**: Python standard library, runs under user `launchd`; collector-specific cadence, timeout/backoff, bounded workers, config hot reload, atomic mode-0600 snapshots, restart persistence, manual refresh requests, sleep/wake catch-up.
- **Collectors**: Gmail labels, Microsoft Graph mail folders, GitHub notification threads, Yahoo IMAP STATUS, Jira JQL approximate count, Slack *one DM*, a read-only experimental macOS Dock badge observer, external versioned executables.
- **Security**: tokens and refresh tokens via macOS Keychain helper, never through command arguments or JSON snapshots. No token scraping, browser profile access, or read-state mutations.
- **Demo**: an explicitly labeled simulated view without credentials or network requests.

## Install on macOS 14+

Requires Xcode Command Line Tools (`xcode-select --install`) and Python 3.10+ (for example, Homebrew Python). Open Terminal in this extracted directory:

```bash
./scripts/test.sh
./scripts/install-mac.sh
```

This compiles `Signals.app` and two native helpers, installs the UI at `~/Applications/Signals.app`, copies the Python coordinator to `~/Library/Application Support/NotificationWidget/project`, creates local config and launches two **user** `launchd` agents. No `sudo`, no third-party Python packages, no Docker and no cloud service needed.

The example configuration begins with **all collectors disabled**, so an installed but unconfigured app displays dashes rather than fabricated zeros. Confluence appears as unsupported, not silently counted. Once launched, use the menu bar bell to show/hide Signals or open the JSON config. Drag the panel anywhere to save its position.

**Preview the design without granting credentials**:

```bash
export PYTHONPATH="$HOME/Library/Application Support/NotificationWidget/project"
python3 -m notifydock.cli demo
open -a "$HOME/Applications/Signals.app"
```

Every preview count is labeled *demo*. If the launch agent is already running, it can overwrite the preview with the configured (disabled/live) state; temporarily stop the agent if you need a stable screenshot. No provider integration is activated by the demo.

## Connect real sources

This is the shortest path to the first genuine two-source milestone. The following commands apply after installation.

```bash
export PYTHONPATH="$HOME/Library/Application Support/NotificationWidget/project"
python3 -m notifydock.cli channel list
```

**GitHub**: Create a **classic** personal access token with the least necessary **`notifications`** scope (fine-grained PATs are not supported by the notifications endpoint). Enter it in a hidden prompt:

```bash
python3 -m notifydock.cli secret set github:personal
python3 -m notifydock.cli channel enable 9
python3 -m notifydock.cli run --once
python3 -m notifydock.cli status
```

**Gmail**: Create a Google Cloud OAuth *Desktop* client with Gmail API enabled and download its client JSON; use the account of your choice with `gmail.labels` scope. Run the local PKCE browser flow; the refresh token is stored in Keychain. Change the example `account` and `secret_ref` to your real account first.

```bash
python3 -m notifydock.cli auth google \
  --ref oauth:gmail:me@gmail.com \
  --client-json "$HOME/Downloads/google-desktop-oauth.json"
python3 -m notifydock.cli channel enable 3
python3 -m notifydock.cli run --once
```

Important: the OAuth example is illustrative. The `client-json` is not bundled, and Google Cloud projects may need consent-screen setup, test-user enrollment, or domain-admin approval. Tokens in Google projects using the consent screen's Testing status may expire sooner.

**Microsoft 365/Outlook**: Register an Entra public client app with delegated `Mail.ReadBasic`, allow public-client device code, choose an appropriate account/tenant type, then:

```bash
python3 -m notifydock.cli auth microsoft \
  --ref oauth:outlook:work@example.com \
  --client-id YOUR_REGISTERED_PUBLIC_CLIENT_ID --tenant common
python3 -m notifydock.cli channel enable 2
```

For corporate accounts, Microsoft/Google/Slack/Atlassian API access can require administrator consent. Avoid asking for broader scopes as a workaround. The coordinator never attempts to access credentials from connected ChatGPT apps or your browser profile.

**Others**: Yahoo uses a Yahoo app password and `IMAP STATUS (UNSEEN)`; Jira uses an Atlassian Cloud API token and a clearly named *matching JQL issues* metric; Slack `conversations.info` supports one authorized **DM conversation**'s displayed unread count, not a workspace total. The Dock observer must be given macOS Accessibility permission and can return *unavailable* or a *limited app badge* (not guaranteed unread count). See [setup details](docs/SETUP_AND_AUTH.md).

## Inspect and change configuration

```bash
python3 -m notifydock.cli channel list                # includes stable channel IDs
python3 -m notifydock.cli channel enable 9            # enable GitHub
python3 -m notifydock.cli channel disable 4           # disable WhatsApp
python3 -m notifydock.cli channel move 9 0            # GitHub first
python3 -m notifydock.cli channel remove 10           # remove sample Slack DM
python3 -m notifydock.cli channel add --file my-channel.json
python3 -m notifydock.cli refresh                     # request refresh (respects API limits)
python3 -m notifydock.cli status                      # read snapshot
```

Or edit:

`~/Library/Application Support/NotificationWidget/config.json`

The coordinator reloads valid edits without restarting. To add another account on a provider, duplicate and edit the channel with a distinct `account`, `scope`, or `metric`. Change click-through URLs from the example placeholders to your approved account destinations. Identity is `provider + account + scope + metric`, with a stable hash ID. A renamed display label does **not** change identity.

The coordinator checks configuration once a second; the panel reads local changes via filesystem notifications and fallback polling. Refresh commands do not override a provider's `X-Poll-Interval` or `Retry-After` header.

## Architecture and tests

```text
[Official API] [IMAP] [Dock AX] [external JSON collector]
       \        |        |       /
       [ Python scheduler + Keychain ]          (launchd)
                    |
        ~/Library/Application Support/
          NotificationWidget/snapshot.json       (atomic, 0600)
                    |
         [Signals.app / SwiftUI panel]           (menu bar + floating window)
```

Tests run on Linux or macOS:

```bash
./scripts/test.sh
PYTHONPATH=. python3 -m notifydock.cli --config examples/config.example.json \
  --snapshot /tmp/signals-demo.json demo
```

See [collector contract](docs/COLLECTOR_CONTRACT.md), [capability matrix](docs/CAPABILITY_MATRIX.md), [ADR](docs/ARCHITECTURE_DECISIONS.md), [security model](docs/SECURITY.md), and [manual macOS verification checklist](docs/MAC_VERIFICATION.md).

## Important limitations

1. The Mac UI and Dock AX helper have not been compiled or visually inspected on the target Mac; a macOS build and smoke test remain mandatory.
2. Real provider credentials and organizational access are not available in this offline source environment. No live provider integration has been demonstrated here.
3. Webex, WhatsApp, Discord and Slack *global* counts rely on optional native Dock observation rather than official equivalent APIs. Dock badges vary by installation and OS, and may represent mentions instead of messages. No badge **does not imply zero** by default.
4. Confluence Cloud's notification drawer is not exposed as a suitable documented public count API. It is listed unsupported until an authorized source is identified. Jira JQL counts are **approximately** matching issues, not notifications.
5. A native WidgetKit desktop widget is not included. A small always-present AppKit panel is more suitable for minute-scale source-specific updates; see ADR.

## Uninstall

```bash
./scripts/uninstall-mac.sh
```

Uninstall deliberately preserves local configuration, snapshots, and Keychain credentials. Delete them manually if you want complete data removal.

**License:** MIT (see [LICENSE](LICENSE)). Third-party names/trademarks belong to their respective owners.
