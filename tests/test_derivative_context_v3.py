import unittest
from tradebot.derivative_context_v3 import features,normalize_series
from tradebot.bitcoin_strategies_v3 import RULES,evaluate
NOW=1800000000
class DerivativeTests(unittest.TestCase):
    def test_funding_constant_and_reversal(self):
        end=NOW//3600*3600
        rows=[dict(time=end-(74-i)*3600,close=.01) for i in range(74)]
        self.assertEqual(features(rows,[],[],as_of=NOW)["funding_variation_status"],"constant_baseline")
        for i,r in enumerate(rows[:-2]): r["close"]=(-1)**i*.01
        rows[-2]["close"]=-.04; rows[-1]["close"]=-.01
        f=features(rows,[],[],as_of=NOW)
        self.assertAlmostEqual(f["funding_prior_z"],-4)
        rule=next(r for r in RULES if r.id=="B20")
        self.assertEqual(evaluate(rule,dict(f,close=101,ema9=100))["directions"],["LONG"])
        rows[-2]["close"]=.04; rows[-1]["close"]=.01
        self.assertEqual(evaluate(rule,dict(features(rows,[],[],as_of=NOW),close=99,ema9=100))["directions"],["SHORT"])
        self.assertIsNone(features(rows[:-1],[],[],as_of=NOW)["funding_latest_z"])
    def test_aligned_basis_and_gaps(self):
        m=[dict(time=NOW-600,close=99.8),dict(time=NOW-300,close=100.9)]
        i=[dict(time=NOW-600,close=100),dict(time=NOW-300,close=101)]
        f=features([],m,i,as_of=NOW)
        self.assertAlmostEqual(f["basis_prior_bps"],-20)
        rule=next(r for r in RULES if r.id=="B22")
        self.assertEqual(evaluate(rule,dict(f,sample_flow_imbalance=.5))["directions"],["LONG"])
        self.assertIsNone(features([],m,i[:-1],as_of=NOW)["basis_bps"])
        self.assertEqual(normalize_series(m+[dict(time=NOW,close=200)],"mark:5m",as_of=NOW),m)
        with self.assertRaises(ValueError): normalize_series(m+m,"mark:5m",as_of=NOW)
        with self.assertRaises(ValueError): normalize_series([dict(time=NOW-300,close=-1)],"index:5m",as_of=NOW)
