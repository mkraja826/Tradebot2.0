import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.m15_account_connectivity_v3 import tick
from test_signed_account_context_v3 import Broker,NOW
class M15AccountTests(unittest.TestCase):
    def test_partial_and_signed_are_separate(self):
        with TemporaryDirectory() as d:
            def reader():
                return {"BTCUSD":{"symbol":"BTCUSD","subaccount":"BTC","status":"partial","signed_account_verified":True,"net_equity_usd":"100","positions":[],"open_order_count":0,"halted":True}}
            x=tick(d,reader=reader,clock=lambda:NOW)
            b=x["markets"]["BTCUSD"]
            self.assertTrue(b["dashboard"]["equity_observed"])
            self.assertFalse(b["dashboard"]["signed_wallet_receipt_verified"])
            self.assertEqual(b["signed_client_status"],"not_provisioned")
            x=tick(d,reader=reader,children={"BTCUSD":Broker()},parent=Broker(parent=True),clock=lambda:NOW)
            b=x["markets"]["BTCUSD"]
            self.assertEqual(b["signed_client_status"],"verified_read_only")
            self.assertTrue(b["signed"]["usd_wallet_available_balance_observed"])
            self.assertTrue(b["signed"]["configured_leverage_observed"])
            self.assertFalse(b["signed"]["maximum_leverage_verified"])
            self.assertFalse(b["commissioning_complete"])
            self.assertFalse(x["execution_authorized"])
            self.assertTrue(b["dashboard"]["halted"])
            self.assertTrue((Path(d)/"m15-account-connectivity-v3.json").exists())
    def test_missing_and_cross_account(self):
        with TemporaryDirectory() as d:
            x=tick(d,reader=lambda:{},children={"BTCUSD":Broker()},parent=Broker("XAUTUSD",parent=True),clock=lambda:NOW)
            self.assertTrue(x["markets"]["BTCUSD"]["signed_client_status"].startswith("unavailable:"))
            self.assertIsNone(x["markets"]["BTCUSD"]["signed"])
            self.assertFalse(x["markets"]["XAUTUSD"]["dashboard"]["identity_verified"])
