import unittest
from recover_trading.execution_cost import fees,closed_cost,spread_sample,build
class ExecutionCostTests(unittest.TestCase):
    def test_fee_turnover_and_identity(self):
        p={"id":84,"symbol":"BTCUSD","contract_value":"0.001","notional_type":"vanilla","settling_asset":{"symbol":"USD"},"quoting_asset":{"symbol":"USD"}}
        f={"id":"a","product_symbol":"BTCUSD","product_id":84,"size":10,"price":"50000","commission":"0.25","settling_asset_symbol":"USD","created_at":"2026-11-25T00:00:00Z"}
        r=fees([f,f,{**f,"id":"b","product_id":85}],p,"BTCUSD")
        self.assertEqual(r["samples"],1)
        self.assertEqual(r["excluded"],2)
        self.assertEqual(r["turnover_weighted_one_way_fee_bps"],5)
    def test_gross_fee_ratio(self):
        self.assertEqual(closed_cost({"gross_pnl":"2","fees":"3","net_before_funding":"-1"})["commission_pct_of_positive_aggregate_gross"],150)
        self.assertIsNone(closed_cost({"gross_pnl":"-1","fees":"1","net_before_funding":"-2"})["commission_pct_of_positive_aggregate_gross"])
    def test_spread_dedup_and_future(self):
        def q(t):return t,{"timestamp_us":t,"bid":99,"ask":101}
        r=spread_sample([q(60000000),q(61000000),q(120000000),q(181000000)],180)
        self.assertEqual(r["samples"],2)
        self.assertEqual(r["median_full_spread_bps"],200)
    def test_funding_not_imputed(self):
        r=build("BTCUSD",{"recent_episodes":[{"decision_id":"d","reported_funding":"0"},{}]}, {},[],{},[],180)
        self.assertEqual(r["funding"]["reported_field_present"],1)
        self.assertEqual(r["funding"]["missing_field"],1)
        self.assertIsNone(r["funding"]["signed_total"])
