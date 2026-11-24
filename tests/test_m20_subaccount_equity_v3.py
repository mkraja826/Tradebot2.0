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
