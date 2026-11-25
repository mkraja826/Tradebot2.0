import unittest
from recover_trading.historical_submission_evidence import classify
class HistoricalSubmissionTests(unittest.TestCase):
    def test_missing_not_terminal(self):
        orders=[("a","unknown",{},{"category":"http_error","http_status":400}),("b","unknown",{},{}),("c","unknown",{},{}),("d","submitting",{}, {})]
        missing={"http_status":400,"exchange_code":"order_not_found"}
        snapshots=[(100,{"order_lookup_diagnostics":{"a":missing,"b":missing,"c":missing}}),(100,{"order_lookup_diagnostics":{"a":missing}}),(101,{"order_lookup_diagnostics":{"c":{"category":"timeout"}}})]
        r=classify(orders,snapshots,{})
        self.assertEqual(r["counts"]["original_http_400_and_lookup_not_found"],1)
        self.assertEqual(r["counts"]["lookup_not_found_original_outcome_unverified"],1)
        self.assertEqual(r["counts"]["insufficient_or_conflicting_lookup_evidence"],2)
        self.assertEqual(r["rows"][0]["distinct_not_found_observation_times"],1)
        self.assertEqual(r["rows"][0]["journal_status"],"unknown")
    def test_matching_order_precedence(self):
        r=classify([("a","unknown",{"product_id":84,"side":"sell"},{})],[],{"a":{"order":{"id":42,"client_order_id":"a","product_id":84,"side":"sell"}}})
        self.assertEqual(r["rows"][0]["classification"],"exchange_order_observed_review_required")
