import unittest,hashlib
from recover_trading.decision_review import review
class DecisionReviewTests(unittest.TestCase):
    def test_receipt_fill_and_signed_deviation(self):
        d={"id":"d","created":1,"model":"fixture","status":"proposed","context":{"demo_account":{"product":{"symbol":"BTCUSD","id":1}}},"result":{"action":"trade","side":"sell","entry_reference":100,"stop_loss":105,"take_profit":90}}
        client=hashlib.sha256(b"recover:d").hexdigest()[:32]
        orders={client:{"status":"acknowledged","detail":{"id":3,"client_order_id":client,"product_id":1,"side":"sell"}}}
        f={"order_id":3,"product_id":1,"side":"sell","size":"2","price":"99","created_at":"2026-11-25T00:00:00Z"}
        a=review([d],orders,[f],[],"BTCUSD")["recent"][0]
        self.assertAlmostEqual(a["entry_deviation_bps"],100)
        self.assertEqual(a["planned_reward_risk"],2)
        self.assertEqual(a["outcome"],"fill_observed_closure_unattributed")
        a=review([d],orders,[f],[{"decision_id":"d","net_before_funding":"1"}],"BTCUSD")["recent"][0]
        self.assertEqual(a["outcome"],"closed_reconciled")
        f["side"]="buy"
        self.assertEqual(review([d],orders,[f],[],"BTCUSD")["recent"][0]["outcome"],"fill_identity_unverified")
    def test_failures_separate_from_unknown_orders(self):
        d={"id":"d","created":1,"model":"fixture","status":"failed","result":{"error":"TimeoutError"}}
        a=review([d],{},[],[],"BTCUSD")
        self.assertEqual(a["failure_counts"],{"TimeoutError":1})
        self.assertEqual(a["outcome_counts"],{"decision_failed":1})
