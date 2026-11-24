import unittest
from datetime import datetime,timezone
from tradebot.delta import DEMO_API
from tradebot.equity_receipt import SOURCE
from tradebot.signed_account_context_v3 import read_signed_context
from test_model_wire_v3 import raw
NOW=datetime(2026,11,24,6,tzinfo=timezone.utc)
T=int(NOW.timestamp()*1e6)
class Broker:
    base_url=DEMO_API
    allow_orders=False
    def __init__(self,symbol="BTCUSD",parent=False):
        self.symbol=symbol; self.parent=parent; self.calls=[]; self.cached=False
    def _request(self,method,path,auth=False):
        assert method=="GET"; self.calls.append(path)
        pid=84 if self.symbol=="BTCUSD" else 181689
        if path=="/v2/users/trading_preferences": value={"user_id":1 if self.parent else 2,"margin_mode":"isolated"}
        elif path=="/v2/sub_accounts": value=[{"id":2,"margin_mode":"isolated","account_name":"BTC" if self.symbol=="BTCUSD" else "GOLD"}]
        elif path=="/v2/products/"+self.symbol: value=raw(self.symbol)
        elif path==f"/v2/products/{pid}/orders/leverage": value={"product_id":pid,"leverage":"10"}
        elif path=="/v2/positions/margined": value=[]
        else: raise AssertionError(path)
        return {"result":value}
    def open_orders(self): return []
    def wallet_balances(self):
        return {"meta":{"net_equity":"100"},"balances":[{"asset_symbol":"USD","available_balance":"80"}],
                "equity_read_receipt":{"source":SOURCE,"equity_usd":"100","request_started_us":T-1000000,
                "received_us":T,"server_date_us":T,"elapsed_us":1000000,"cache_age_seconds":int(self.cached),"response_sha256":"a"*64}}
class SignedAccountTests(unittest.TestCase):
    def test_both_assets(self):
        for s in ("BTCUSD","XAUTUSD"):
            b=Broker(s); p=Broker(s,parent=True)
            x=read_signed_context(s,b,p,clock=lambda:NOW)
            self.assertEqual(x["available_margin_usd"],"80")
            self.assertEqual(x["configured_leverage"],"10")
            self.assertTrue(x["wallet_receipt_verified"])
            self.assertFalse(x["execution_authorized"])
            self.assertIsNone(x["leverage_limit"])
    def test_reject_wrong_or_cached(self):
        b=Broker(); p=Broker(parent=True)
        b.cached=True
        with self.assertRaises(ValueError): read_signed_context("BTCUSD",b,p,clock=lambda:NOW)
        b.cached=False
        with self.assertRaises(ValueError): read_signed_context("BTCUSD",b,Broker("XAUTUSD",parent=True),clock=lambda:NOW)
        with self.assertRaises(ValueError): read_signed_context("BTCUSD",b,None,clock=lambda:NOW)
        b.allow_orders=True
        with self.assertRaises(ValueError): read_signed_context("BTCUSD",b,p,clock=lambda:NOW)

    def test_reject_foreign_order_even_when_flat(self):
        b=Broker(); p=Broker(parent=True)
        b.open_orders=lambda:[{"product_symbol":"XAUTUSD","product_id":181689,"state":"open"}]
        with self.assertRaises(ValueError): read_signed_context("BTCUSD",b,p,clock=lambda:NOW)
        b.open_orders=lambda:[{"product_symbol":"BTCUSD","product_id":84,"state":"open"}]
        x=read_signed_context("BTCUSD",b,p,clock=lambda:NOW)
        self.assertEqual(x["open_order_states"],{"open":1,"pending":0})
        self.assertEqual(x["available_margin_basis"],"usd_wallet_available_balance_not_broker_order_margin_quote")
        self.assertFalse(x["execution_authorized"])
        b.open_orders=lambda:[{"product_symbol":"BTCUSD","state":"open"}]
        with self.assertRaises(ValueError): read_signed_context("BTCUSD",b,p,clock=lambda:NOW)
