import unittest
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_mark_aggregation import aggregate,audit

class AggregationTests(unittest.TestCase):
    def test_exact_ohlc(self):
        a=[Bar(300,10,13,9,12,0),Bar(600,12,15,11,14,0),Bar(900,14,14,8,9,0)]
        self.assertEqual(aggregate(a,900),[Bar(900,10,15,8,9,0)])
    def test_partial_edges_excluded(self):
        a=[Bar(t,10,12,9,11,0) for t in range(600,2101,300)]
        self.assertEqual([b.ts for b in aggregate(a,900)],[1800])
    def test_gap_rejected(self):
        with self.assertRaises(ValueError):aggregate([Bar(300,10,12,9,11),Bar(900,10,12,9,11)],900)
    def test_native_anomaly_visible(self):
        fine=[Bar(t,100,101,99,100,0) for t in range(300,225001,300)]
        derived=aggregate(fine,900)
        native=list(derived)
        b=native[100];native[100]=Bar(b.ts,100,150,99,100,0)
        x=audit(native,derived,seconds=900,as_of=225000)
        self.assertEqual(x["native_anomalies"],1)
        self.assertEqual(x["aggregated_anomalies"],0)
        self.assertEqual(x["matched_bars"],250)
        self.assertEqual(x["max_ohlc_difference"],49)
        self.assertEqual(x["aggregated_quality"],"observed")
