import unittest
from unittest.mock import Mock, patch
from recover_trading.lr_v4b_local_sizing import local_sizing
from recover_trading.lr_v4b_controller import Controller
from recover_trading.lr_v4b_execution import submit
from recover_trading.engine import Journal
from recover_trading.execution import DemoExecutor
from recover_trading.management_executor import ManagementExecutor
from test_recover_execution import Fake
import time


class LocalBroker(Fake):
    def _request(self,method,path,**kw):
        r=super()._request(method,path,**kw)
        if path.startswith("/v2/products/"):
            r.update(tick_size="0.5",contract_unit_currency="BTC",notional_type="vanilla",
                     settling_asset={"symbol":"USD"},quoting_asset={"symbol":"USD"})
        if path.startswith("/v2/tickers/"):
            r["quotes"]={"best_bid":"99.5","best_ask":"100"}
        return r


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.b=LocalBroker()
        self.j=Journal(":memory:")
        self.addCleanup(self.j.close)
        self.e=DemoExecutor(self.b,self.j)
        self.p=Mock()
        self.c=Controller(self.e,ManagementExecutor(self.b,self.j),self.p,"fixture","/unused",local=True)
        t=int(time.time())//60*60
        self.signal={"version":"lr-v4b","symbol":"BTCUSD","signal_time":t,"burst_time":t,"side":"buy","initial_stop":95}
        self.flat={"positions":[],"active_orders":[],"active_orders_complete":True}
    def test_formula_and_available_margin(self):
        from recover_trading.execution import account_context
        a=account_context(self.b,"BTCUSD")
        p=local_sizing(self.signal,a)
        self.assertEqual(p["size"],40000)
        self.assertEqual(p["capital_allocation"],200)
        self.assertEqual(p["leverage"],20)
        a["wallets"][0]["available_balance"]="200"
        self.assertEqual(local_sizing(self.signal,a)["reason"],"insufficient_available_margin_for_target")
    def test_contract_rounding(self):
        from recover_trading.execution import account_context
        a=account_context(self.b,"BTCUSD")
        a["decision_quote"]["best_ask"]="60000"
        p=local_sizing(self.signal,a)
        self.assertEqual(p["size"],66)
        self.assertEqual(p["capital_allocation"],198)
    def test_missing_settlement_wallet(self):
        from recover_trading.execution import account_context
        a=account_context(self.b,"BTCUSD")
        a["wallets"][0]["asset_symbol"]="INR"
        with self.assertRaises(ValueError):
            local_sizing(self.signal,a)
    def test_controller_without_ai(self):
        t=self.signal["signal_time"]
        with patch("recover_trading.lr_v4b_controller.time.time",return_value=t+1), \
             patch("recover_trading.lr_v4b_controller.submit",side_effect=lambda *args,**kw:submit(*args,**kw,clock=lambda:t+1)):
            out=self.c.enter({"status":"observed","recent_signal":self.signal},self.flat)
        self.assertEqual(out["decision"]["ai_calls"],0)
        self.assertEqual(out["execution"]["status"],"acknowledged")
        self.assertEqual(out["execution"]["sizing"]["contracts"],40000)
        self.p._propose.assert_not_called()
        order=next(k["payload"] for m,p,k in self.b.calls if m=="POST" and p=="/v2/orders")
        self.assertEqual(order["size"],40000)
        self.assertEqual(float(order["bracket_stop_loss_price"]),95)
        self.assertEqual(float(order["bracket_take_profit_price"]),110)
