import unittest
from tradebot.liquidation_research_v3 import parse_external_batch,evidence_readiness
NOW=1800000000000
def message():
    return {"topic":"allLiquidation.BTCUSDT","type":"snapshot","ts":NOW-100,
            "data":[{"T":NOW-200,"s":"BTCUSDT","S":s,"v":"0.01","p":"60000"} for s in ("Buy","Sell")]}
class LiquidationResearchTests(unittest.TestCase):
    def test_position_side_and_scope(self):
        r=parse_external_batch(message(),received_ms=NOW)
        self.assertEqual([e["liquidated_position_side"] for e in r["events"]],["LONG","SHORT"])
        self.assertFalse(r["delta_demo_evidence"])
        self.assertFalse(r["coverage_complete"])
        self.assertFalse(r["strategy_activation_authorized"])
    def test_missing_stale_wrong(self):
        for k,v in (("s","ETHUSDT"),("S","buy"),("v","NaN"),("p","-1"),("T",NOW+1)):
            m=message(); m["data"][0][k]=v
            with self.assertRaises(ValueError): parse_external_batch(m,received_ms=NOW)
        with self.assertRaises(ValueError): parse_external_batch(message(),received_ms=NOW+10001)
        with self.assertRaises(ValueError): parse_external_batch(dict(message(),data=[]),received_ms=NOW)
    def test_no_activation(self):
        for status in (200,403,None):
            r=evidence_readiness(delta_has_liquidation_flag=False,external_http_status=status)
            self.assertFalse(r["continuous_coverage_verified"])
            self.assertEqual(set(r["strategies"].values()),{"deferred"})
            self.assertFalse(r["execution_authorized"])
