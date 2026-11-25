import unittest
from recover_trading.engine import Journal, OrderIntent
from recover_trading.lifecycle import Lifecycle, order_state, pages
from test_recover_execution import Fake

class Broker(Fake):
    def margined_positions(self, pid):
        return [{"product_id":pid,"size":10,"margin":"5","unrealized_pnl":"2"}]
    def active_orders_page(self, pid, after=None):
        return {"result":[{"product_id":pid,"side":"sell","state":"pending",
                           "reduce_only":True,"stop_price":"95","stop_order_type":"stop_loss_order"},
                          {"product_id":pid,"side":"sell","state":"pending",
                           "reduce_only":True,"stop_price":"105","stop_order_type":"take_profit_order"}]}
    def fills_page(self, pid, after=None):
        return {"result":[{"id":"fill-1","product_id":pid,"order_id":"42",
                           "settling_asset_symbol":"USD","commission":"0.1",
                           "meta_data":{"new_position":{"size":0,"realized_pnl":"3"},"ip":"secret"}}]}
    def order(self, client_id):
        return {"id":42,"client_order_id":client_id,"product_id":1,
                "size":10,"unfilled_size":4,"state":"open"}

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.journal = Journal(":memory:")
        self.addCleanup(self.journal.close)
        self.broker = Broker()
        self.lifecycle = Lifecycle(self.broker,self.journal)
    def test_snapshot_deduplicates_fills_and_tracks_partial(self):
        self.journal.begin("entry","BTCUSD",OrderIntent(1,"buy",10))
        self.journal.finish("entry","acknowledged",{"id":42})
        first = self.lifecycle.refresh("BTCUSD")
        self.assertEqual(first["bracket_evidence"],"both_legs_observed")
        self.assertEqual(first["positions"][0]["margin"],"5")
        self.assertEqual(first["new_fills"],1)
        self.assertEqual(self.lifecycle.refresh("BTCUSD")["new_fills"],0)
        row = self.journal.db.execute("SELECT detail FROM observed_fills").fetchone()[0]
        self.assertNotIn("secret",row)
        self.assertIn("position_flat_after_fill",row)
        row = self.journal.db.execute("SELECT detail FROM observed_orders").fetchone()[0]
        self.assertIn('"status": "partial"',row)
    def test_failed_position_read_is_not_flat(self):
        def fail(pid):
            raise OSError()
        self.broker.margined_positions = fail
        r = self.lifecycle.refresh("BTCUSD")
        self.assertNotIn("positions",r)
        self.assertEqual(r["bracket_evidence"],"unverified")
    def test_order_states(self):
        self.assertEqual(order_state({"size":10,"unfilled_size":0,"state":"closed"})["status"],"filled")
        self.assertEqual(order_state({"size":10,"unfilled_size":5,"state":"cancelled"})["status"],"cancelled_partial")
        self.assertEqual(order_state({"state":"closed"})["status"],"unverified")
    def test_pagination(self):
        def fetch(pid,after):
            return {"result":[{"product_id":pid}], "meta":{"after":"next"} if not after else {}}
        self.assertEqual(len(pages(fetch,1)[0]),2)
        self.assertFalse(pages(fetch,1,limit=1)[1])
