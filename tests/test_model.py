import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from notifydock.config import read_config
from notifydock.model import ChannelConfig, Reading, failed_result, initial_result, successful_result
from notifydock.snapshot import atomic_json, load_snapshot, write_snapshot


EXAMPLE = Path(__file__).resolve().parent.parent / 'examples' / 'config.example.json'


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.gmail = {
            'provider': 'gmail', 'account': 'one@company.com', 'scope': 'INBOX',
            'metric': 'unread_messages', 'display_name': 'One', 'collector': 'gmail',
            'enabled': True, 'url': 'https://mail.google.com/'
        }

    def test_multiple_accounts_get_different_stable_ids(self):
        a = ChannelConfig.from_dict(self.gmail)
        b = ChannelConfig.from_dict({**self.gmail, 'account': 'two@company.com'})
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(a.id, ChannelConfig.from_dict(self.gmail).id)
        self.assertTrue(a.id.startswith('ch_'))

    def test_scope_and_metric_are_identity(self):
        a = ChannelConfig.from_dict(self.gmail)
        b = ChannelConfig.from_dict({**self.gmail, 'scope': 'STARRED'})
        c = ChannelConfig.from_dict({**self.gmail, 'metric': 'unread_threads'})
        self.assertEqual(len({a.id, b.id, c.id}), 3)

    def test_metric_mismatch_rejected(self):
        for bad in [
            {**self.gmail, 'metric': 'unread_notification_threads'},
            {**self.gmail, 'refresh_seconds': 0},
            {**self.gmail, 'enabled': 'true'},
            {**self.gmail, 'url': 'javascript:alert(1)'},
            {**self.gmail, 'url': 'https://username:pass@other.com/path'},
            {**self.gmail, 'url': 'file:///private/etc/passwd'},
            {**self.gmail, 'url': None},
            {**self.gmail, 'account': 'one\x1ftwo'},
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ChannelConfig.from_dict(bad)

    def test_badge_requires_app_name(self):
        with self.assertRaises(ValueError):
            ChannelConfig.from_dict({**self.gmail, 'collector': 'dock_badge', 'metric': 'application_badge'})

    def test_external_requires_absolute_executable(self):
        with self.assertRaises(ValueError):
            ChannelConfig.from_dict({**self.gmail, 'collector': 'external', 'settings': {'command': ['python3']}})

    def test_all_example_channels_and_unique_ids(self):
        channels = read_config(EXAMPLE)
        self.assertEqual(len(channels), 11)
        self.assertEqual(len(set(c.id for c in channels)), len(channels))
        self.assertEqual(len({c.provider for c in channels}), 10)
        self.assertFalse(any(c.enabled for c in channels))

    def test_duplicate_identity_prohibited(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'config.json'
            target.write_text(json.dumps({'version': 1, 'channels': [self.gmail, self.gmail]}))
            with self.assertRaises(ValueError):
                read_config(target)

    def test_count_zero_vs_none_and_bool(self):
        self.assertEqual(Reading(0).count, 0)
        self.assertEqual(Reading(None, 'unknown').count, None)
        for count in (True, -1, 1.7):
            with self.assertRaises(ValueError):
                Reading(count)
        with self.assertRaises(ValueError):
            Reading(None, 'exact')

    def test_failure_keeps_last_observation(self):
        ch = ChannelConfig.from_dict(self.gmail)
        ok = successful_result(ch, Reading(7), '2026-10-14T12:00:00Z')
        failed = failed_result(ch, ok, 'auth_required', 'Token expired', '2026-10-14T12:30:00Z')
        self.assertEqual(failed['count'], 7)
        self.assertEqual(failed['observed_at'], ok['observed_at'])
        self.assertEqual(failed['last_success_at'], ok['last_success_at'])
        self.assertEqual(failed['checked_at'], '2026-10-14T12:30:00Z')

    def test_unsupported_explicit_not_disabled(self):
        ch = next(c for c in read_config(EXAMPLE) if c.provider == 'confluence')
        self.assertEqual(initial_result(ch)['status'], 'unsupported')

    def test_atomic_snapshot_private_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'nested' / 'snapshot.json'
            write_snapshot(target, [initial_result(ChannelConfig.from_dict(self.gmail))])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(len(load_snapshot(target)['channels']), 1)
            write_snapshot(target, [])
            self.assertEqual(load_snapshot(target)['channels'], [])
            self.assertFalse(list(target.parent.glob('.snapshot-*')))
            self.assertNotIn('secret_ref', target.read_text())


if __name__ == '__main__': unittest.main()
