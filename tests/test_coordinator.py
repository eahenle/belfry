import json
import tempfile
import time
import unittest
from pathlib import Path

from notifydock.coordinator import Coordinator
from notifydock.http import AuthRequired, CollectorError
from notifydock.keychain import Keychain
from notifydock.model import ChannelConfig, Reading
from notifydock.snapshot import load_snapshot


class Clock:
    def __init__(self): self.t = 1000
    def __call__(self): return self.t
    def move(self, sec): self.t += sec


def entry(account, refresh=60):
    return {'provider':'gmail', 'account':account, 'scope':'INBOX',
            'metric':'unread_messages', 'display_name':account,
            'refresh_seconds':refresh, 'enabled':True, 'collector':'gmail'}


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.config=root/'config.json'
        self.snapshot=root/'snapshot.json'
        self.refresh=root/'refresh.request'
        self.clock=Clock()

    def setup_coordinator(self, accounts, collector):
        self.config.write_text(json.dumps({'version':1,'channels':[entry(a) for a in accounts]}))
        c=Coordinator(self.config,self.snapshot,self.refresh,collector=collector,
                      keychain=object(),clock=self.clock)
        self.addCleanup(c.close)
        return c

    @staticmethod
    def wait_done(coord):
        for _ in range(100):
            coord.tick()
            if all(s.future is None for s in coord.slots.values()):
                return
            time.sleep(0.005)
        raise AssertionError('futures did not finish')

    def test_multiple_accounts_partial_failure(self):
        def collect(ch, keychain):
            if ch.account=='work': raise AuthRequired('no token')
            return Reading(11)
        c=self.setup_coordinator(['work','personal'],collect)
        self.wait_done(c)
        rows=load_snapshot(self.snapshot)['channels']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['status'],'auth_required')
        self.assertIsNone(rows[0]['count'])
        self.assertEqual(rows[1]['count'],11)
        self.assertEqual(rows[1]['status'],'ok')

    def test_stale_last_good_survives_failure_and_restart(self):
        state={'fail':False}
        def collect(ch, keychain):
            if state['fail']: raise CollectorError('network down')
            return Reading(12)
        c=self.setup_coordinator(['personal'],collect)
        self.wait_done(c)
        first=load_snapshot(self.snapshot)['channels'][0]
        state['fail']=True
        self.clock.move(61)
        self.wait_done(c)
        after=load_snapshot(self.snapshot)['channels'][0]
        self.assertEqual(after['count'],12)
        self.assertEqual(after['status'],'error')
        self.assertEqual(after['last_success_at'],first['last_success_at'])
        c2=Coordinator(self.config,self.snapshot,self.refresh,collector=collect,
                       keychain=object(),clock=self.clock)
        self.addCleanup(c2.close)
        persisted=load_snapshot(self.snapshot)['channels'][0]
        self.assertEqual(persisted['count'],12)
        self.assertEqual(persisted['status'],'error')

    def test_none_result_does_not_discard_previous_count(self):
        state={'none':False}
        def collect(ch, keychain):
            return Reading(None, 'unknown', 'API returned no count') if state['none'] else Reading(42)
        c=self.setup_coordinator(['personal'],collect)
        self.wait_done(c)
        state['none']=True
        self.clock.move(70)
        self.wait_done(c)
        row=load_snapshot(self.snapshot)['channels'][0]
        self.assertEqual(row['count'],42)
        self.assertEqual(row['status'],'unavailable')

    def test_backoff_and_retry_after(self):
        calls=[]
        def collect(ch, keychain):
            calls.append(self.clock())
            raise CollectorError('rate limited',retry_after=270)
        c=self.setup_coordinator(['personal'],collect)
        self.wait_done(c)
        slot=next(iter(c.slots.values()))
        self.assertEqual(slot.next_due, 1270)
        self.clock.move(100)
        c.force_refresh()
        c.tick()
        self.assertEqual(len(calls),1)
        self.clock.move(171)
        self.wait_done(c)
        self.assertEqual(len(calls),2)

    def test_provider_poll_interval_maintained(self):
        calls=[]
        def collect(ch, keychain):
            calls.append(self.clock())
            return Reading(4,min_refresh_seconds=180)
        c=self.setup_coordinator(['personal'],collect)
        self.wait_done(c)
        self.clock.move(59)
        c.force_refresh()
        c.tick()
        self.assertEqual(len(calls),1)
        self.clock.move(120)
        self.wait_done(c)
        self.assertEqual(len(calls),1)
        self.clock.move(2)
        self.wait_done(c)
        self.assertEqual(len(calls),2)

    def test_live_config_reorder_enable_disable(self):
        c=self.setup_coordinator(['one','two'],lambda ch, keychain: Reading(2))
        self.wait_done(c)
        data={'version':1,'channels':[{'provider':'gmail', 'account':'three','scope':'INBOX',
               'metric':'unread_messages','display_name':'three','enabled':False},entry('two')]}
        self.config.write_text(json.dumps(data))
        c.reload(force=True)
        rows=load_snapshot(self.snapshot)['channels']
        self.assertEqual([r['account'] for r in rows],['three','two'])
        self.assertEqual(rows[0]['status'],'disabled')
        self.assertEqual(rows[1]['count'],2)

    def test_restart_honors_persisted_provider_minimum(self):
        c=self.setup_coordinator(['one'],lambda ch, keychain: Reading(4, min_refresh_seconds=180))
        self.wait_done(c)
        c2=Coordinator(self.config,self.snapshot,self.refresh,
                       collector=lambda ch,keychain: Reading(9),
                       keychain=object(),clock=self.clock)
        self.addCleanup(c2.close)
        slot=next(iter(c2.slots.values()))
        self.assertEqual(slot.min_refresh, 180)
        self.assertGreater(slot.next_due, self.clock()+150)

    def test_sleep_wake_clock_translation(self):
        calls=[]
        def collect(ch,keychain):
            calls.append(self.clock())
            return Reading(4, min_refresh_seconds=180)
        c=self.setup_coordinator(['one'],collect)
        self.wait_done(c)
        self.assertEqual(len(calls),1)
        # In a Mac suspend scenario wall clock advances while monotonic barely moves.
        c._last_wall -= 7200
        c.tick()
        self.wait_done(c)
        self.assertEqual(len(calls),2)

    def test_unsupported_metric_rejected_preserving_last_valid(self):
        c=self.setup_coordinator(['one'],lambda ch, keychain: Reading(2))
        self.wait_done(c)
        self.config.write_text(json.dumps({'version':1,'channels':[{'provider':'gmail','account':'one',
                     'scope':'INBOX','metric':'totally made up','display_name':'one'}]}))
        self.assertFalse(c.reload(force=True))
        self.assertEqual(len(c.channels),1)
        self.assertEqual(load_snapshot(self.snapshot)['channels'][0]['count'],2)


if __name__ == '__main__': unittest.main()
