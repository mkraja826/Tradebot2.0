import unittest
from tempfile import TemporaryDirectory
from tradebot.admin_review_v3 import review
class ReviewTests(unittest.TestCase):
    def test_missing(self):
        with TemporaryDirectory() as d:
            r=review(d,now=1000)
            self.assertEqual(set(r['markets']),{'BTCUSD','XAUTUSD'})
            self.assertTrue(all(v['status']=='unavailable' for v in r['markets'].values()))
            self.assertFalse(r['execution_authorized'])
            self.assertFalse(r['production_policy_replaced'])
            self.assertEqual(len(r['policy_source_hashes']),2)
