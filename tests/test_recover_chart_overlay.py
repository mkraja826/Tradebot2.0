import unittest
from recover_trading.chart_overlay import build
class ChartOverlayTests(unittest.TestCase):
    def test_verified_lines_and_fill_classification(self):
        s="BTCUSD";now=1795618300
        pos={"product_id":84,"product_symbol":s,"size":-2,"entry_price":"100","mark_price":"99","unrealized_pnl":"2"}
        snap={"symbol":s,"observed":now,"positions":[pos]}
        prev={"symbol":s,"observed":now,"size":"-2","position_state":"short","bracket_state":"matching_legs_observed","legs":[{"type":"stop_loss_order","trigger":"105"},{"type":"take_profit_order","trigger":"95"}]}
        cost={"status":"commission_only_estimate","direction":"SHORT","entry_price":"100","remaining_contracts":"2","break_even_exit_fill_price":"99.9"}
        f={"id":"a","product_id":84,"product_symbol":s,"side":"sell","size":2,"price":100,"created_at":"2026-11-25T00:00:00Z","new_position":{"size":-2}}
        r=build(s,snap,prev,cost,[f,{**f,"id":"b","side":"buy","new_position":{"size":0}},f,{**f,"id":"wrong","product_id":181689}],{},now)
        self.assertEqual({l["kind"] for l in r["lines"]},{"entry","mark","stop","target","break_even"})
        self.assertEqual([x["kind"] for x in r["fills"]],["entry","exit"])
        self.assertEqual(r["status"],"position_observed")
        self.assertEqual(build(s,snap,prev,cost,[f],{},now+181)["lines"],[])
        prev["bracket_state"]="unverified"
        self.assertEqual({l["kind"] for l in build(s,snap,prev,cost,[],{},now)["lines"]},{"entry","mark","break_even"})
    def test_flat_no_current_lines(self):
        p={"symbol":"XAUTUSD","observed":10,"position_state":"flat"}
        r=build("XAUTUSD",{"symbol":"XAUTUSD","observed":10,"positions":[]},p,{},[],{},10)
        self.assertEqual(r["status"],"flat");self.assertEqual(r["lines"],[])
