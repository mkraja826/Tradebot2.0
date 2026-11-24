import unittest
from unittest.mock import patch
from tradebot.m20_subaccount_performance_v3 import project
class ForwardPerformanceTests(unittest.TestCase):
 def base(self):
    return dict(subaccount="BTC",observed_at="2026-11-24T10:33:00+00:00",opening_equity_usd="100")
 def current(self):
    return dict(symbol="BTCUSD",subaccount="BTC",observed_at="2026-11-24T10:34:00+00:00",signed_account_verified=True,wallet_receipt_verified=True,net_equity_usd="150",product={"product_id":84})
 def row(self,**kw):
    return dict(dict(id="1",at_us=1795516410000000,product_id=None,asset="USD",type="sub_account_transfer",amount="50"),**kw)
 @patch("tradebot.m20_subaccount_performance_v3.normalize_posting",side_effect=lambda x:x)
 def test_transfer(self,m):
    r=project("BTCUSD",self.base(),self.current(),[self.row()])
    self.assertEqual(r["adjusted_equity_change_usd"],"0")
    self.assertFalse(r["execution_authorized"])
    self.assertFalse(r["is_verified_return"])
 @patch("tradebot.m20_subaccount_performance_v3.normalize_posting",side_effect=lambda x:x)
 def test_unknown(self,m):
    r=project("BTCUSD",self.base(),self.current(),[self.row(type="conversion")])
    self.assertIsNone(r["adjusted_equity_change_usd"])
 def test_identity(self):
    a=self.current();a["wallet_receipt_verified"]=False
    with self.assertRaises(ValueError):project("BTCUSD",self.base(),a,[])
 @patch("tradebot.m20_subaccount_performance_v3.normalize_posting",side_effect=lambda x:x)
 def test_wrong_product(self,m):
    with self.assertRaises(ValueError):project("BTCUSD",self.base(),self.current(),[self.row(product_id="999")])
