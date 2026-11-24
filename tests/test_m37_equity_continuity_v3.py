"""Offline migration continuity regression; never grants release authority."""
import unittest
from tradebot.m33_policy_candidate_v3 import replay
from test_m25_equity_policy_research_v3 import val,flow
S='BTCUSD'; I='synthetic-btc'
class ContinuityTests(unittest.TestCase):
    def check(self,events):
        r=replay(S,I,events)
        for k in ('historical_loss_reconciled','broker_evidence_verified','execution_authorized','policy_deployed'):
            self.assertIs(r[k],False)
        return r
    def test_breach_survives_full_week_rollover(self):
        events=[val(1,'100',offset=1),val(2,'90',offset=2)]
        for i,t in enumerate(range(120,604801,120),3):
            events.append(val(i,'100',offset=t))
        r=self.check(events)
        self.assertEqual(r['status'],'fixture_evaluated')
        self.assertTrue(r['daily_opening_observed'])
        self.assertTrue(r['weekly_opening_observed'])
        self.assertEqual(r['observed_breach_history'],['daily','sampled_drawdown','weekly'])
    def test_missed_daily_window_no_backfill(self):
        events=[val(i+1,'100',offset=t) for i,t in enumerate(range(1,86400,120))]
        events.append(val(99999,'100',offset=86701))
        r=self.check(events)
        self.assertFalse(r['daily_opening_observed'])
        self.assertIn('observation_gap',r['uncertainty'])
        self.assertEqual(r['status'],'continuity_unresolved')
    def test_initial_transfer_without_anchor(self):
        r=self.check([flow(1,'100','200','100'),val(2,'200')])
        self.assertIn('missing_prior_valuation',r['uncertainty'])
        self.assertIsNone(r['last_known_index'])
    def test_unknown_history_cannot_be_healed_by_deposit(self):
        r=self.check([val(1,'100'),val(2,'90'),dict(val(3,'90'),kind='unknown'),flow(4,'90','1090','1000'),val(5,'1090')])
        self.assertEqual(r['last_known_index'],'0.9')
        self.assertIn('unknown_event',r['uncertainty'])
        self.assertIn('daily',r['observed_breach_history'])
    def test_same_timestamp_or_wrong_account_refused(self):
        for events in ([val(1,'100'),val(1,'90')],[val(1,'100'),dict(val(2,'90'),fixture_account='synthetic-other')]):
            with self.assertRaises(ValueError):replay(S,I,events)
