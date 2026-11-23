"""Privacy-safe evidence counts for ambiguous signed wallet postings."""
import json
import unittest
from tradebot.isolated_performance import _overlap_evidence_summary


class OverlapEvidenceTests(unittest.TestCase):
    def setUp(self):
[redacted potentially sensitive output]
[redacted potentially sensitive output]
        self.product={"id":27}
        self.fills=[
[redacted potentially sensitive output]
[redacted potentially sensitive output]
[redacted potentially sensitive output]
[redacted potentially sensitive output]
                "type":"commission","amount":"-9876.54321",
[redacted potentially sensitive output]
[redacted potentially sensitive output]

    def test_unknown_broker_references_are_counted_not_attributed(self):
        result=_overlap_evidence_summary(
            self.trade,self.product,self.fills,[self.p])
        self.assertEqual(result["overlapping_same_product_postings"],1)
        self.assertEqual(result["explicitly_referenced_unattributed"],1)
        self.assertEqual(result["unmatched_order_references"],1)
        self.assertEqual(result["unmatched_fill_references"],1)
        self.assertEqual(result["commission_postings"],1)
        self.assertFalse(result["is_verified_trade_pnl"])

    def test_unreferenced_funding_is_not_assumed_zero(self):
        p={**self.p,"order_id":None,"fill_id":None,"type":"funding"}
        result=_overlap_evidence_summary(
            self.trade,self.product,self.fills,[p])
        self.assertEqual(result["unreferenced"],1)
        self.assertEqual(result["funding_postings"],1)
        self.assertFalse(result["is_verified_trade_pnl"])

    def test_different_product_and_outside_trade_are_not_counted(self):
        p1={**self.p,"product_id":"999"}
        p2={**self.p,"at_us":100}
        result=_overlap_evidence_summary(
            self.trade,self.product,self.fills,[p1,p2])
        self.assertEqual(result["overlapping_same_product_postings"],0)

    def test_report_does_not_disclose_identifiers_or_amounts(self):
        result=_overlap_evidence_summary(
            self.trade,self.product,self.fills,[self.p])
        raw=json.dumps(result)
[redacted potentially sensitive output]
            self.assertNotIn(value,raw)
        self.assertEqual(_overlap_evidence_summary({}, {}, [], [])["status"],
                         "unavailable")


if __name__=="__main__":
    unittest.main()