import unittest
from tradebot.trade_flow_v3 import project, inputs

class FlowTests(unittest.TestCase):
    def test_old_trades_outside_window_not_counted(self):
        now=1_800_000_000_000_000
        def row(age):
            return dict(symbol="BTCUSD",timestamp=now-age*1_000_000,
                        buyer_role="taker",seller_role="maker",size=1,price=100)
        r=project([row(i*3) for i in range(25)]+[row(400+i) for i in range(25)],"BTCUSD",now)
        self.assertEqual(r["sample_count"],25)
        self.assertEqual(r["sample_imbalance"],1)
        with self.assertRaises(ValueError):
            project([row(i*3) for i in range(19)]+[row(400+i) for i in range(31)],"BTCUSD",now)

    def test_book_independent_of_missing_flow(self):
        self.assertEqual(inputs({"book":{"imbalance":.2,"spread_bps":3}}),
                         {"book_imbalance":.2,"book_spread_bps":3})
