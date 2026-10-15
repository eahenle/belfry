# Platform connection guide

All following commands assume installation was completed and:

```bash
export PYTHONPATH="$HOME/Library/Application Support/NotificationWidget/project"
python3 -m notifydock.cli channel list
```

Indices below refer to the **initial example file**. After removing/reordering channels, use `channel list` to find current indices or stable IDs. The `--ref` or `secret set` names must match that channel's `secret_ref` in `config.json`.

## Gmail (index 3)

1. In Google Cloud Console, create/select a project, enable Gmail API, configure OAuth consent for your account, and create **Desktop** OAuth client credentials. Download the JSON, keep it outside this repository.
2. In config, change `account`, `secret_ref` and optionally `url` to the correct Google account. `scope=INBOX`, `metric=unread_messages` is a label counter. For thread counts, switch `metric=unread_threads` and relabel it.
3. Run `python3 -m notifydock.cli auth google --client-json /private/path/client_secret.json --ref oauth:gmail:me@gmail.com`. Google sign-in opens and returns to local loopback callback. PKCE code verifier/state are generated per request; no OAuth callback server stays running.
4. Run `python3 -m notifydock.cli channel enable 3`, then `... run --once` and `... status`.
5. If the account or organization blocks unverified OAuth apps, request appropriate authorization rather than expanding API scopes.

## Microsoft Outlook 365 / Outlook.com (index 2)

1. Register a public client Microsoft Entra app, allow personal and/or organization accounts as appropriate. Enable delegated `Mail.ReadBasic` and public-client device-code flow. For an employer tenant you may need admin approval.
2. Change `account` and `secret_ref` in config. Choose `scope=inbox` or a Graph folder ID. The metric is `unread_mail_items`, not total notifications.
3. `python3 -m notifydock.cli auth microsoft --client-id YOUR_APP_ID --tenant common --ref oauth:outlook:work@example.com`. Visit the displayed device-login URL and enter the displayed one-time code. OAuth refresh token is stored in Keychain. You can choose `--tenant organizations` or a tenant ID for a work-specific flow.
4. Enable channel 2.

## GitHub (index 9)

Create a **classic personal access token**, with notifications scope and any necessary organization SSO authorization, in GitHub settings. *Fine-grained PAT tokens cannot use GitHub's REST list-notifications endpoint.* Run `python3 -m notifydock.cli secret set github:personal`, enter token in hidden prompt, enable index 9. It pages `GET /notifications` without marking anything read and obeys GitHub's `X-Poll-Interval`. More than 2,000 threads produce an honest lower-bound, not a false exact total.

## Yahoo Mail (index 6)

Yahoo Account Security → External connections → Generate app password, if eligible. Change config to your full Yahoo address; `secret set yahoo:me@yahoo.com` stores the app password in Keychain. Enable index 6. Only `STATUS INBOX (UNSEEN)` over IMAPS with `export.imap.mail.yahoo.com:993` is issued. It neither selects a message nor changes seen flags.

## Jira Cloud (index 7)

Create an Atlassian Cloud API token according to employer policy. Change config `account` (email), `secret_ref`, `url` (human-facing) and `settings.site` (`https://company.atlassian.net`). Keep a precise `settings.jql` query, such as `assignee = currentUser() AND resolution = Unresolved`. Run `secret set jira:work@example.com` and enable index 7. Jira displays **approximate number of matching issues**, deliberately different from unread notifications. The site must be an `*.atlassian.net` HTTPS host.

## Slack (indices 1 or 10)

- **Dock global badge (index 1):** Enable only after testing native Accessibility below. This is `application_badge`, not a Slack API unread total. Badge settings may hide numbers.
- **Single DM (index 10):** Create/install a Slack app with a user-scoped access token authorized for `conversations.info` on DMs (typically `im:read`). Put a real `D...` conversation ID into `settings.channel_id`, update scope from sample `DM:D0123456789`, update account, `url`, `secret_ref`. Store authorized Slack user token with `secret set slack:my-workspace`. Enable. A workspace-wide unread count is **not supported by this API path**; adding every DM separately may be wasteful/rate-limited. Employer app approvals apply.

## Webex, WhatsApp, Discord (indices 0, 4, 5)

Only the Dock observer is implemented. The Mac app must be installed/running with an icon in the Dock, the `settings.app_name` must match the Accessibility title, and macOS must expose a numeric `AXStatusLabel`. To opt in:

1. Locate `~/Library/Application Support/NotificationWidget/bin/dock-badge` in Finder using **Go → Go to Folder…**.
2. In **System Settings → Privacy & Security → Accessibility**, add/allow this binary (and confirm authorization if macOS prompts). Grant only if you're comfortable with a process reading app accessibility labels. You may need to restart the helper/app or re-add permission after a rebuild.
3. Test in Terminal: `"$HOME/Library/Application Support/NotificationWidget/bin/dock-badge" "Webex"`; repeat for WhatsApp or Discord. It prints a JSON object, e.g. `{ "state": "numeric_badge", "count": 3 }`. No result or `no_badge` does **not** mean zero.
4. Enable the channel, watch for `badge` vs `unavailable`. Leave unsupported if no reliable reading.

`settings.no_badge_is_zero=true` explicitly opts into interpreting an unbadged Dock icon as zero, but the reading is marked `limited` and can be wrong if badge display is disabled. Default is **false**.

## Confluence (index 8)

No appropriate public unread notification count method identified. Remains `unsupported`. Do not enable a fabricated JQL count as a substitute. An approved future collector can use the `external` protocol with an explicitly different metric if valid.

## Additional channels

To add a second Gmail account, copy an entry, change `account` and `secret_ref`, authorize independently, and enable it. To add another type, prepare a single JSON channel object and run `channel add --file /path/channel.json`, then review IDs/order. To remove, use `channel remove`. The UI loads configuration changes automatically.

## Troubleshooting

`auth_required` means the Keychain item is missing, inaccessible, expired or rejected. `unavailable` means no count was obtained, **not** zero. `error` is a timed-out/rate-limited/broken collector; previous count remains visible. For logs, inspect `~/Library/Logs/NotificationWidget/coordinator-error.log`; the log intentionally contains no tokens. If the Keychain appears locked under launchd, manually invoke `run --once` from Terminal first to resolve macOS authorization prompts for the helper.
