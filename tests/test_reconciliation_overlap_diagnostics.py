"""Privacy-safe evidence counts for ambiguous signed wallet postings."""
import json
import unittest
from tradebot.isolated_performance import (
    _overlap_evidence_summary, _signed_fill_uuid_alias_probe,
    _unattributed_evidence_summary,
)


class OverlapEvidenceTests(unittest.TestCase):
    def setUp(self):
        # Synthetic test-only order/fill identities and microsecond timestamps.
        self.trade = {"broker_order_id": "101", "exit_order_ids": {"stop": "102"}}
        self.product = {"id": 27}
        self.fills = [
            {"id": "201", "order_id": "101", "at_us": 10},
            {"id": "202", "order_id": "102", "at_us": 30},
        ]
        self.p = {"product_id": "27", "at_us": 20,
                  "type": "commission", "amount": "-9876.54321",
                  "order_id": "999001", "fill_id": "999002"}

    def test_unknown_broker_references_are_counted_not_attributed(self):
        result=_overlap_evidence_summary(
            self.trade,self.product,self.fills,[self.p])
        self.assertEqual(result["overlapping_same_product_postings"],1)
        self.assertEqual(result["explicitly_referenced_unattributed"],1)
        self.assertEqual(result["present_order_references"],1)
        self.assertEqual(result["present_fill_references"],1)
        self.assertEqual(result["known_foreign_order_references"],0)
        self.assertEqual(result["known_foreign_fill_references"],0)
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

    def test_signed_explicit_uuid_alias_links_wallet_commission(self):
        alias = "123e4567-e89b-12d3-a456-426614174000"
        report = _signed_fill_uuid_alias_probe(
            [{"id": 100, "meta_data": {"fill_uuid": alias}}],
            [{"transaction_type": "commission",
              "meta_data": {"fill_uuid": alias}}])
        self.assertEqual(report["signed_fill_id_is_uuid"], 0)
        self.assertEqual(report["signed_fill_rows_with_explicit_alias"], 1)
        self.assertEqual(report["uuid_identity_intersection"], 1)
        self.assertNotIn(alias, json.dumps(report))
        self.assertFalse(report["is_verified_trade_pnl"])

    def test_unmatched_wallet_uuid_is_not_inferred(self):
        report = _signed_fill_uuid_alias_probe(
            [{"id": 100, "meta_data": {}}],
            [{"transaction_type": "commission",
              "meta_data": {"fill_uuid":
                  "123e4567-e89b-12d3-a456-426614174000"}}])
        self.assertEqual(report["wallet_commission_uuid_references"], 1)
        self.assertEqual(report["uuid_identity_intersection"], 0)
        self.assertEqual(report["signed_fill_rows_with_explicit_alias"], 0)

    def test_unknown_uuid_is_not_a_valid_alias(self):
        report = _signed_fill_uuid_alias_probe(
            [{"id": "a", "uuid": "not-a-valid-id"}],
            [{"transaction_type": "commission",
              "fill_uuid": "not-a-valid-id"}])
        self.assertEqual(report["uuid_identity_intersection"], 0)
        self.assertEqual(report["wallet_commission_uuid_references"], 0)

    def test_after_flat_unreferenced_funding_is_reported_without_pnl(self):
        posting={**self.p,"at_us":100,"type":"funding",
                 "order_id":None,"fill_id":None}
        d=_unattributed_evidence_summary(
            self.trade,self.product,self.fills,[posting])
        self.assertEqual(d["status"],"timing_counts_only")
        self.assertEqual(d["nonowned_after_flat_fill"],1)
        self.assertEqual(d["after_flat_without_order_or_fill_ref"],1)
        self.assertEqual(d["after_flat_funding"],1)
        self.assertFalse(d["is_verified_trade_pnl"])
        self.assertNotIn("-9876.54321", json.dumps(d))

    def test_known_owned_posting_after_close_not_counted_as_foreign(self):
        posting={**self.p,"at_us":101,
                 "order_id":"102","fill_id":"202"}
        d=_unattributed_evidence_summary(
            self.trade,self.product,self.fills,[posting])
        self.assertEqual(d["nonowned_since_entry"],0)
        self.assertEqual(d["nonowned_after_flat_fill"],0)

    def test_report_does_not_disclose_identifiers_or_amounts(self):
        result=_overlap_evidence_summary(
            self.trade,self.product,self.fills,[self.p])
        raw=json.dumps(result)
        for value in ("999001", "999002", "-9876.54321"):
            self.assertNotIn(value,raw)
        self.assertEqual(_overlap_evidence_summary({}, {}, [], [])["status"],
                         "unavailable")


if __name__=="__main__":
    unittest.main()