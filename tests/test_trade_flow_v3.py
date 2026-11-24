import unittest
from tradebot.trade_flow_v3 import project,inputs
NOW=1800000000000000
class FlowTests(unittest.TestCase):
    def test_sample(self):
        rows=[dict(symbol="BTCUSD",timestamp=NOW-i*1000000,buyer_role="taker",seller_role="maker",size=2,price="100") for i in range(20)]
        x=project(rows,"BTCUSD",NOW)
        self.assertEqual(x["sample_imbalance"],1)
        self.assertFalse(x["complete_interval"])
        b=dict(timestamp_us=NOW,imbalance=.3,spread_bps=1)
        self.assertEqual(inputs({"book":b,"flow":x})["sample_flow_imbalance"],1)
        self.assertEqual(inputs({"book":dict(b,timestamp_us=NOW-61000000),"flow":x}),{})
        rows[0]["symbol"]="XAUTUSD"
        with self.assertRaises(ValueError): project(rows,"BTCUSD",NOW)
        rows[0]["symbol"]="BTCUSD"; rows[0]["buyer_role"]="maker"
        with self.assertRaises(ValueError): project(rows,"BTCUSD",NOW)
