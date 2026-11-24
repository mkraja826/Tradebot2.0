import unittest
from datetime import datetime,timezone,timedelta
from tradebot.equity_policy_v3 import evaluate_index
from tradebot.equity_policy_reference_v3 import stamp

class NativeEquityEvaluation(unittest.TestCase):
    opening=datetime(2026,11,23,tzinfo=timezone.utc)
    def evaluate(self,amounts,offset=0):
        rows=[(stamp(self.opening+timedelta(seconds=offset+i*60)),v) for i,v in enumerate(amounts)]
        return evaluate_index(rows,now=self.opening+timedelta(seconds=offset+len(amounts)*60))
    def test_exact_threshold_and_recovery(self):
        result=self.evaluate(['100','98','100'])['periods']
        self.assertTrue(result['daily']['observed_breach'])
        self.assertEqual(result['daily']['current_loss'],'0')
        self.assertEqual(result['daily']['maximum_loss'],'0.02')
    def test_distinct_limits(self):
        p=self.evaluate(['100','95','92','101'])['periods']
        for k in ('daily','weekly','drawdown'):self.assertTrue(p[k]['observed_breach'])
        self.assertEqual(p['drawdown']['maximum_loss'],'0.08')
    def test_missing_opening_not_zero(self):
        p=self.evaluate(['100','100'],offset=301)['periods']
        self.assertIsNone(p['daily']['observed_breach'])
        self.assertIsNone(p['weekly']['current_loss'])
    def test_decline_from_peak(self):
        p=self.evaluate(['100','125','115'])['periods']
        self.assertEqual(p['drawdown']['maximum_loss'],'0.08')
        self.assertFalse(p['daily']['observed_breach'])
    def test_no_authority_and_stale_samples(self):
        r=self.evaluate(['100','100'])
        self.assertFalse(r['execution_authorized'])
        self.assertEqual(r['latest_age_seconds'],60)
    def test_duplicate_timestamp(self):
        t=stamp(self.opening)
        with self.assertRaises(ValueError):evaluate_index([(t,'100'),(t,'99')],now=self.opening)
