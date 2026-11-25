import unittest
from tradebot.m20_subaccount_equity_v3 import analyse
class SubaccountEquityTests(unittest.TestCase):
 def p(self,kind,amount,s="BTCUSD",i="a"):
    return dict(symbol=s,at_us=2,id=i,type=kind,asset="USD",amount=amount)
 def calc(self,rows,**kw):
    return analyse("BTCUSD","100","150",rows,start_us=1,end_us=3,**kw)
 def test_transfer_not_profit(self):
    r=self.calc([self.p("sub_account_transfer","50")],complete=True)
    self.assertEqual(r["adjusted_equity_change_usd"],"0")
    self.assertFalse(r["execution_authorized"])
 def test_fees_and_funding(self):
    r=self.calc([self.p("sub_account_transfer","55"),self.p("commission","-3",i="b"),self.p("funding","-2",i="c")],complete=True)
    self.assertEqual(r["adjusted_equity_change_usd"],"-5")
    self.assertEqual(r["posted_trading_cashflow_usd"],"-5")
 def test_incomplete_unknown(self):
    self.assertIsNone(self.calc([])["adjusted_equity_change_usd"])
    self.assertIsNone(self.calc([self.p("conversion","50")],complete=True)["adjusted_equity_change_usd"])
 def test_cross_account_duplicate(self):
    for rows in ([self.p("deposit","50","XAUTUSD")],[self.p("deposit","50")]*2):
        with self.assertRaises(ValueError):self.calc(rows,complete=True)
 def test_gold_withdrawal(self):
    r=analyse("XAUTUSD","100","80",[self.p("sub_account_transfer","-20","XAUTUSD")],start_us=1,end_us=3,complete=True)
    self.assertEqual(r["adjusted_equity_change_usd"],"0")

 def test_miscellaneous_keeps_known_losses_and_unknown_values(self):
    rows=[self.p("conversion","50"),self.p("commission","-3",i="b"),dict(self.p("conversion","20",i="c"),asset="EUR")]
    r=self.calc(rows,complete=True);m=r["miscellaneous"]
    self.assertEqual(r["status"],"unclassified_postings")
    self.assertIsNone(r["adjusted_equity_change_usd"])
    self.assertEqual(m["known_unclassified_usd"],"50")
    self.assertEqual(m["known_posted_trading_cashflow_usd"],"-3")
    self.assertEqual(m["unconverted_posting_count"],1)
    self.assertEqual(m["historical_missing_valuations"],"unknown")
    self.assertEqual(m["eligible_trading_credit_usd"],"0")
    self.assertFalse(r["execution_authorized"])
 def test_miscellaneous_incomplete_window_never_assumes_zero(self):
    r=self.calc([]);self.assertIsNone(r["miscellaneous"]["known_unclassified_usd"])
    self.assertIsNone(r["miscellaneous"]["unexplained_or_unrealized_usd"])
 def test_miscellaneous_is_subaccount_scoped(self):
    r=analyse("XAUTUSD","100","90",[self.p("conversion","-10","XAUTUSD")],start_us=1,end_us=3,complete=True)
    self.assertEqual(r["miscellaneous"]["known_unclassified_usd"],"-10")
    self.assertFalse(r["parent_equity_included"])
