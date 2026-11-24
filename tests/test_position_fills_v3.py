import unittest
from copy import deepcopy
from tradebot.position_fills_v3 import fill_progress,completed_trade
from tradebot.fire_reconciliation import normalize_fill,normalize_posting,ReconciliationError
from test_fire_reconciliation import Broker,BASE,NOW
class PositionFillTests(unittest.TestCase):
    def test_partial_and_complete(self):
        for s in ("BTCUSD","XAUTUSD"):
            b=Broker(s)
            for count,state,remaining in ((0,"no_entry_fill","0"),(2,"entry_fills_observed","2"),(3,"partial_exit_observed","1"),(4,"exit_fills_observed","0")):
                r=fill_progress(s,27,"LONG","100",["101","102"],b.fills[:count])
                self.assertEqual(r["status"],state)
                self.assertEqual(r["remaining_contracts"],remaining)
                self.assertFalse(r["settlement_verified"])
                self.assertIsNone(r["net_realized_pnl_usd"])
    def test_duplicate_and_wrong_scope(self):
        b=Broker()
        r=fill_progress("BTCUSD",27,"LONG","100",["101"],b.fills+[b.fills[0]])
        self.assertEqual(r["entered_contracts"],"2")
        with self.assertRaises(ValueError): fill_progress("XAUTUSD",27,"LONG","100",["101"],b.fills)
        with self.assertRaises(ValueError): fill_progress("BTCUSD",27,"LONG","100",["101"],b.fills[2:])
    def test_verified_settlement_fixture(self):
        for s in ("BTCUSD","XAUTUSD"):
            b=Broker(s)
            f=[normalize_fill(x) for x in b.fills]; p=[normalize_posting(x) for x in b.postings]
            end=int(NOW.timestamp()*1000000)
            x=completed_trade(s,b.trade,b.product,b.orders,f,p,BASE,end)
            self.assertEqual(x["evidence"]["net_realized_pnl_usd"],"0.075")
            self.assertFalse(x["execution_authorized"])
            with self.assertRaises((ValueError,ReconciliationError)): completed_trade(s,b.trade,b.product,b.orders,f,p[:-1],BASE,end)
