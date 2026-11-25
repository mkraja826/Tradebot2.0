import unittest
from recover_trading.postfill_bracket import audit
class PostfillBracketTests(unittest.TestCase):
    def test_short_target_above_fill_and_missing_legs(self):
        s={"symbol":"BTCUSD","observed":1000,"positions":[{"product_id":84,"size":-25,"entry_price":"58880"}],"active_orders":[],"active_orders_complete":True}
        r={"id":42,"product_id":84,"side":"sell","state":"closed","size":25,"unfilled_size":0,"bracket_stop_loss_price":"60180","bracket_take_profit_price":"59450"}
        f={"id":"f","order_id":42,"product_id":84,"side":"sell","size":25,"price":"58880"}
        a=audit(s,"BTCUSD",1001,[r],[f])
        self.assertEqual(a["status"],"bracket_evidence_missing_or_mismatched")
        self.assertFalse(a["entry_evidence"]["bracket_price_geometry"])
        self.assertIsNone(audit(s,"BTCUSD",1001,[r],[f,f])["entry_evidence"])
        self.assertIsNone(audit(s,"BTCUSD",1200,[r],[f])["entry_evidence"])
        r["bracket_take_profit_price"]="58000"
        self.assertTrue(audit(s,"BTCUSD",1001,[r],[f])["entry_evidence"]["bracket_price_geometry"])
