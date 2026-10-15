import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from notifydock.http import AuthRequired, CollectorError, Unsupported
from notifydock.keychain import SecretUnavailable
from notifydock.model import ChannelConfig
from notifydock.providers import collect, github, gmail, outlook, yahoo, jira, slack, dock_badge, external


class FakeKeychain:
    def __init__(self, values=None): self.values = values or {}
    def get(self, ref):
        if ref not in self.values: raise SecretUnavailable('missing')
        return self.values[ref]
    def set(self, ref, value): self.values[ref] = value


def channel(provider, metric, **values):
    return ChannelConfig.from_dict({
        'provider': provider, 'account': 'person@example.com', 'scope': 'INBOX',
        'metric': metric, 'display_name': provider,
        'secret_ref': 'secret-ref', 'enabled': True, **values
    })


class ProviderTests(unittest.TestCase):
    def test_gmail_labels_get_is_read_only(self):
        c = channel('gmail', 'unread_messages')
        with patch('notifydock.oauth.access_token', return_value='access'), \
             patch('notifydock.http.request_json', return_value=({'messagesUnread': 5, 'threadsUnread': 3}, {})) as http:
            r = gmail(c, FakeKeychain())
            self.assertEqual(r.count, 5)
            self.assertEqual(r.precision, 'exact')
            self.assertIn('users/me/labels/INBOX', http.call_args.args[0])
            self.assertIsNone(http.call_args.kwargs.get('data'))
        c = channel('gmail', 'unread_threads')
        with patch('notifydock.oauth.access_token', return_value='access'), \
             patch('notifydock.http.request_json', return_value=({'messagesUnread': 5, 'threadsUnread': 3}, {})):
            self.assertEqual(gmail(c, FakeKeychain()).count, 3)

    def test_outlook_is_folder_unread_count(self):
        c = channel('outlook', 'unread_mail_items', scope='inbox')
        with patch('notifydock.oauth.access_token', return_value='access'), \
             patch('notifydock.http.request_json', return_value=({'unreadItemCount': 12}, {})) as http:
            self.assertEqual(outlook(c, FakeKeychain()).count, 12)
            self.assertIn('mailFolders/inbox?', http.call_args.args[0])
            self.assertEqual(http.call_args.kwargs, {})

    def test_github_pagination_and_poll_header(self):
        c = channel('github', 'unread_notification_threads')
        pages = [([{'id': str(i)} for i in range(100)], {
                  'Link': '<https://api.github.com/notifications?page=2>; rel="next"',
                  'X-Poll-Interval': '180'}),
                 ([{'id': '100'}], {'X-Poll-Interval': '180'})]
        with patch('notifydock.http.request_json', side_effect=pages) as http:
            reading = github(c, FakeKeychain({'secret-ref': 'classic-token'}))
            self.assertEqual(reading.count, 101)
            self.assertEqual(reading.min_refresh_seconds, 180)
            self.assertEqual(http.call_count, 2)
            self.assertTrue(all('notifications?' in ca.args[0] for ca in http.call_args_list))
            self.assertTrue(all('Bearer classic-token' in ca.args[1]['Authorization'] for ca in http.call_args_list))

    def test_github_pagination_safety_cap_is_lower_bound(self):
        c = channel('github', 'unread_notification_threads')
        response = ([{'id':str(i)} for i in range(100)], {
            'Link': '<https://api.github.com/notifications?page=2>; rel="next"'})
        with patch('notifydock.http.request_json', return_value=response) as http:
            reading = github(c, FakeKeychain({'secret-ref': 'token'}))
            self.assertEqual(reading.count, 2000)
            self.assertEqual(reading.precision, 'lower_bound')
            self.assertEqual(http.call_count, 20)

    def test_github_fails_closed_on_unrecognized_pagination_host(self):
        c = channel('github', 'unread_notification_threads')
        with patch('notifydock.http.request_json', return_value=([], {
            'Link': '<https://evil.example/notifications?page=2>; rel="next"'})):
            with self.assertRaises(CollectorError): github(c, FakeKeychain({'secret-ref': 't'}))

    def test_github_no_credentials_is_auth_required(self):
        c = channel('github', 'unread_notification_threads')
        with self.assertRaises(AuthRequired): github(c, FakeKeychain())

    def test_slack_dm_unread_count_only(self):
        c = channel('slack', 'unread_dm_messages', scope='DM:D1', settings={'channel_id': 'D1'})
        with patch('notifydock.http.request_json', return_value=(
            {'ok': True, 'channel': {'is_im': True, 'unread_count_display': 7}}, {})):
            self.assertEqual(slack(c, FakeKeychain({'secret-ref': 't'})).count, 7)
        with patch('notifydock.http.request_json', return_value=(
            {'ok': True, 'channel': {'is_im': False, 'unread_count_display': 7}}, {})):
            with self.assertRaises(Unsupported): slack(c, FakeKeychain({'secret-ref': 't'}))
        with patch('notifydock.http.request_json', return_value=(
            {'ok': True, 'channel': {'is_im': True}}, {})):
            with self.assertRaises(Unsupported): slack(c, FakeKeychain({'secret-ref': 't'}))

    def test_jira_uses_approximate_count_only_and_fixed_site(self):
        c = channel('jira', 'matching_jql_issues', scope='assigned-unresolved',
                    settings={'site': 'https://acme.atlassian.net', 'jql': 'assignee = currentUser() AND resolution = Unresolved'})
        with patch('notifydock.http.request_json', return_value=({'count': 9}, {})) as http:
            reading = jira(c, FakeKeychain({'secret-ref': 'pat'}))
            self.assertEqual(reading.precision, 'approximate')
            self.assertEqual(reading.count, 9)
            self.assertIn('/search/approximate-count', http.call_args.args[0])
            self.assertEqual(http.call_args.args[2]['jql'], c.settings['jql'])
        c = channel('jira', 'matching_jql_issues', settings={'site': 'https://evil.example', 'jql': 'X'})
        with self.assertRaises(Unsupported): jira(c, FakeKeychain({'secret-ref': 'pat'}))

    def test_yahoo_status_does_not_select_or_fetch(self):
        c = channel('yahoo', 'unread_messages')
        client = MagicMock()
        client.status.return_value = ('OK', [b'INBOX (MESSAGES 104 UNSEEN 19)'])
        with patch('imaplib.IMAP4_SSL', return_value=client) as ctor:
            reading = yahoo(c, FakeKeychain({'secret-ref': 'app-password'}))
            self.assertEqual(reading.count, 19)
            client.login.assert_called_once_with(c.account, 'app-password')
            client.status.assert_called_once_with('INBOX', '(UNSEEN)')
            client.fetch.assert_not_called()
            client.select.assert_not_called()
            client.logout.assert_called_once()

    def test_dock_badge_numeric_and_no_badge(self):
        with tempfile.TemporaryDirectory() as td:
            helper = Path(td) / 'dock'
            helper.write_text('#!/bin/sh\necho "{}"\n')
            c = channel('webex', 'application_badge', collector='dock_badge',
                        settings={'helper': str(helper), 'app_name': 'Webex'})
            with patch('subprocess.run') as proc:
                proc.return_value = MagicMock(returncode=0, stdout='{"state":"numeric_badge","count":6}')
                reading = dock_badge(c, FakeKeychain())
                self.assertEqual(reading.count, 6)
                self.assertEqual(reading.precision, 'limited')
                proc.return_value = MagicMock(returncode=0, stdout='{"state":"no_badge"}')
                with self.assertRaises(Exception): dock_badge(c, FakeKeychain())
            c_zero = channel('webex', 'application_badge', collector='dock_badge',
                        settings={'helper': str(helper), 'app_name': 'Webex', 'no_badge_is_zero': True})
            with patch('subprocess.run', return_value=MagicMock(returncode=0, stdout='{"state":"no_badge"}')):
                self.assertEqual(dock_badge(c_zero, FakeKeychain()).count, 0)

    def test_external_result_protocol_no_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            helper = Path(td) / 'collector'
            helper.write_text('''#!/usr/bin/env python3
import json,sys
payload=json.load(sys.stdin)
assert 'secret_ref' not in payload['channel']
print(json.dumps({'version':1,'count':8,'precision':'exact'}))
''')
            helper.chmod(0o700)
            c = channel('other', 'other', collector='external', settings={'command': [str(helper)]})
            self.assertEqual(external(c, FakeKeychain()).count, 8)

    def test_providers_reject_negative_counts(self):
        c = channel('outlook', 'unread_mail_items', scope='inbox')
        with patch('notifydock.oauth.access_token', return_value='a'), \
             patch('notifydock.http.request_json', return_value=({'unreadItemCount': -3}, {})):
            with self.assertRaises(CollectorError): outlook(c, FakeKeychain())


if __name__ == '__main__': unittest.main()
