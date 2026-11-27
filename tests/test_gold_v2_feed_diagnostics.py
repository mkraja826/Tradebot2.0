import unittest
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_feed_diagnostics import anomalies,compare

def bars():
    return [Bar(300*(i+1),100,101,99,100,1) for i in range(100)]
class FeedDiagnosticTests(unittest.TestCase):
    def test_disagreement(self):
        a,b=bars(),bars()
        a[60]=Bar(a[60].ts,100,150,90,100,1)
        x=compare(a,b)
        self.assertEqual(x["demo_anomalies"],1)
        self.assertEqual(x["matched_anomalies"],0)
        self.assertEqual(x["details"][0]["reference_range"],2)
        self.assertEqual(a[60].h,150)
    def test_shared_anomaly(self):
        a=bars();a[60]=Bar(a[60].ts,100,150,90,100,1)
        self.assertEqual(compare(a,a)["matched_anomalies"],1)
    def test_missing_reference(self):
        a=bars();a[60]=Bar(a[60].ts,100,150,90,100,1)
        self.assertEqual(compare(a,[])["unmatched_timestamps"],1)
