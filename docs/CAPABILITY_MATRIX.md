# Official API capability & implementation matrix

**Researched 2026-10-14.** “Implemented” means local source with mocked endpoint tests passing, *not* verified access to a live account. All real integrations need user authorization and sometimes employer approval. macOS native app and Dock observer were source-parsed on Linux, not built or runtime-tested on macOS.

| Requested provider | Defined metric / scope | Official count interface | Credential/permission | Suggested refresh | Shipped status / restriction |
|---|---|---|---|---|---|
| **Gmail** | `unread_messages` or `unread_threads` on a *specific label*, default `INBOX` | `users.labels.get` yields `messagesUnread` / `threadsUnread` | Google OAuth desktop PKCE, `gmail.labels` scope (admin restrictions possible) | 120 s | **Implemented; fixture-tested; OAuth required.** Two metrics kept distinct. |
| **Outlook / Microsoft 365** | `unread_mail_items` in Inbox (or selected mail folder) | Microsoft Graph `/me/mailFolders/{id}` `unreadItemCount` | Delegated `Mail.ReadBasic`, OAuth device code + refresh, Entra app registration. Personal and work accounts supported subject to tenant policy | 120 s | **Implemented; fixture-tested; OAuth required.** Not notification threads or Teams messages. |
| **GitHub** | `unread_notification_threads` across authenticated user | `GET /notifications?all=false`, page until end. Respect `X-Poll-Interval` | Classic PAT with `notifications` scope or approved OAuth app. Endpoint **does not accept fine-grained PATs** | ≥120 s and provider header | **Implemented; fixture-tested; PAT required.** Returns lower bound if 2,000 threads cap hit. GET never marks read. |
| **Yahoo Mail** | `unread_messages` in IMAP folder (`INBOX`) | `STATUS INBOX (UNSEEN)` over IMAPS 993 on `export.imap.mail.yahoo.com` | Yahoo mail address + Yahoo app password, Keychain | 180 s | **Implemented; fixture-tested; app password required.** Read-only IMAP status, no FETCH/SELECT. |
| **Jira Cloud** | `matching_jql_issues` for *explicit JQL*, by default assigned unresolved issues | `POST /rest/api/3/search/approximate-count` | Atlassian Cloud email + API token, Browse Projects permissions, site `*.atlassian.net` | 300 s | **Implemented; fixture-tested; API token required.** **Approximate assigned work items**, not unread notifications. |
| **Slack** | (a) app badge of Slack in Dock, or (b) `unread_dm_messages` for a *particular authorized DM* | API `conversations.info` `unread_count_display` **DM only**, not generalized channels/workspace; Dock option separate | Authorized user token, `im:read`, plus Slack app install/approval, or local macOS Accessibility grant for Dock | 180 s API / 60 s Dock | **Both adapters implemented; fixture-tested.** Workspace/global count not claimed. Native observation unverified. |
| **Webex** | `application_badge` from local Webex Dock icon | Messaging API exposes message list and webhooks but no documented general unread-state count matching the client's UI | Local app present in Dock and macOS Accessibility permission; corp policy may apply | 60 s | **Experimental Dock adapter; Linux fixture only.** No real Webex unread-count API collector claimed. |
| **WhatsApp** | `application_badge` from local WhatsApp Dock icon | Consumer-account unread state has no appropriate documented public API; WhatsApp Business APIs are distinct | Local app + Accessibility permission | 60 s | **Experimental Dock adapter; not verified on macOS.** No session scraping or unofficial automation. |
| **Discord** | `application_badge` from local Discord Dock icon | Bot APIs are not user's personal unread state; self-bots prohibited | Local app + Accessibility permission | 60 s | **Experimental Dock adapter; not verified on macOS.** Never use consumer user tokens for bots. |
| **Confluence Cloud** | Requested unread notification drawer count | No suitable documented public unread count endpoint in Confluence REST API; the drawer can combine Jira notifications | Would require an approved supported integration, not generic Confluence REST alone | N/A | **Explicitly unsupported**. Do not fabricate count or double-count Atlassian shared bell activity. |

## Critical semantic distinctions

- **Gmail** counts either messages or threads inside a label. Label selection changes the scope.
- **Outlook** is unread *mail items* in a folder. Not a cross-app notification center.
- **GitHub** counts notification threads; threads are not messages.
- **Jira** matches JQL and uses a provider-documented **estimated** count. Changing JQL changes what it means.
- **Slack** API DM counts apply only to a specific DM conversation; reading `unread_count_display` from a public channel cannot be assumed. Dock badge is a different metric.
- **Dock badges** might represent unread conversations, mentions, or settings-driven counts. The adapter flags them as `limited`; absence of a numeric badge returns `unavailable` instead of zero by default.
- **Confluence** notification drawer has a distinct unseen count which may clear when opening it, and can overlap Jira. We don't automatically aggregate it.
- **No grand total** across these metric types.

## Corporate vs personal account differences

- Google Workspace can disable APIs or third-party OAuth; Gmail personal accounts use individual OAuth consent but may be constrained by project verification/test status.
- Microsoft consumer Outlook.com and Microsoft 365 work/school support `Mail.ReadBasic` in Graph, but the Entra tenant may restrict app registration/device flow and require admin consent.
- Slack workspace app installation/user scope approval may be required; an app/bot token does not automatically expose a human's per-user DM read state.
- Webex enterprise messaging may be governed by organization policies; local badge observation is not guaranteed to be allowed or useful.
- Atlassian site-scoped access and issue permissions gate Jira search results. Confluence notification overlap requires care.
- GitHub enterprise organizations may require PAT SSO authorization; private/public repositories and enterprise settings affect visibility.

## Official primary sources

- [Gmail `users.labels.get` authorization](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels/get), [label counts](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels)
- [Graph mailFolder read/permissions](https://learn.microsoft.com/en-us/graph/api/mailfolder-get?view=graph-rest-1.0), [mailFolder `unreadItemCount`](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0)
- [GitHub notifications and polling limits](https://docs.github.com/en/rest/activity/notifications)
- [Yahoo official IMAP settings](https://help.yahoo.com/kb/mail/manually-download-yahoo-emails-sln28681.html), [third-party app passwords](https://help.yahoo.com/kb/technical-support/generate-password-access-yahoo-mail-sln15241.html)
- [Jira Cloud approximate count endpoint](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/), [Atlassian exact-vs-approx guidance](https://support.atlassian.com/jira/kb/find-the-total-number-of-work-items-in-jira-cloud-using-jql-or-issue-search/)
- [Slack `conversations.info` response](https://docs.slack.dev/reference/methods/conversations.info/), [Slack user conversations](https://api.slack.com/methods/users.conversations)
- [Webex messages API](https://developer.webex.com/messaging/docs/api/v1/messages), [Webex webhooks](https://developer.webex.com/messaging/docs/webhooks)
- [Discord self-bot prohibition](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)
- [Confluence Cloud REST API reference](https://developer.atlassian.com/cloud/confluence/rest/v1/), [Confluence in-app drawer](https://support.atlassian.com/confluence-cloud/docs/view-your-notifications/), [Atlassian cross-product unseen count](https://support.atlassian.com/atlassian-cloud/kb/overview-of-in-app-notifications-in-atlassian-cloud-products/)

## Status legend

- `ok`: last count observed from chosen adapter, with `precision` and `observed_at`.
- `simulated`: explicitly fake fixtures, never a live count.
- `auth_required`: missing, inaccessible, expired or rejected credentials; retain last successful count if any.
- `error`: request/collector error; retain last successful count.
- `unavailable`: no reliable numeric reading; retain last successful count if any.
- `unsupported`: no implementation offering requested metric.
- `disabled`: not configured for polling.
- `stale`: derived by UI when last observed too long ago (even if previous service status was `ok`).
