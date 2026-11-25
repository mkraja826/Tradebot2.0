import unittest
from recover_trading.performance import account
class PerformanceTests(unittest.TestCase):
    def test_closed_episode_and_legacy_anchor(self):
        spec={"id":1,"notional_type":"vanilla","contract_value":"0.001","settling_asset":{"symbol":"USD"},"quoting_asset":{"symbol":"USD"}}
        def f(i,side,price,after,order,pnl=None,total=None):
            return {"created_at":f"2026-11-25T00:00:0{i}Z","product_id":1,"side":side,"size":"10","price":str(price),"commission":"0.01","settling_asset_symbol":"USD","order_id":order,"new_position":{"size":after,"realized_pnl":pnl,"total_commission_paid":total}}
        rows=[f(1,"sell",100,0,"old"),f(2,"buy",100,10,"entry"),f(3,"sell",110,0,"exit","0.10","0.02")]
        a=account(rows,spec,{"entry":{"decision_id":"d","active_rules":["B01"]}},complete=True)
        self.assertEqual(a["recover_attributed"]["closed_episodes"],1)
        self.assertEqual(a["recover_attributed"]["net_before_funding"],"0.080")
        self.assertEqual(a["active_rule_cooccurrence"]["B01"]["closed_episodes"],1)
        self.assertEqual(account(rows,spec,{},complete=True)["recover_attributed"]["closed_episodes"],0)
        self.assertEqual(account(rows,spec,{},complete=False)["all_reconciled"]["closed_episodes"],0)
        rows[-1]["new_position"]["realized_pnl"]="999"
        self.assertEqual(account(rows,spec,{},complete=True)["all_reconciled"]["closed_episodes"],0)
