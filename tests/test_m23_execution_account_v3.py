import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tradebot.delta import DEMO_API
from tradebot.m23_execution_account_v3 import inspect,project_leverage

class AccountTests(unittest.TestCase):
 def setUp(self):
    self.client=SimpleNamespace(base_url=DEMO_API,allow_orders=False)
    self.a=dict(symbol="BTCUSD",subaccount="BTC",signed_account_verified=True,wallet_receipt_verified=True,observed_at="2026-11-24T11:00:00+00:00",product={"product_id":84})
 @patch("tradebot.m23_execution_account_v3._require_flat_demo_exposure")
 @patch("tradebot.m23_execution_account_v3.read_signed_context")
 def test_readonly(self,read,flat):
    read.return_value=self.a;flat.return_value=dict(account_flat_verified=True,open_positions=0,open_orders=0)
    r=inspect("BTCUSD",self.client,self.client)
    self.assertTrue(r["flat_exposure_verified"]);self.assertFalse(r["execution_client_verified"]);self.assertFalse(r["execution_authorized"])
 @patch("tradebot.m23_execution_account_v3._require_flat_demo_exposure")
 @patch("tradebot.m23_execution_account_v3.read_signed_context")
 def test_wrong_identity(self,read,flat):
    read.return_value=dict(self.a,subaccount="GOLD")
    self.assertFalse(inspect("BTCUSD",self.client,self.client)["identity_verified"]);flat.assert_not_called()
 @patch("tradebot.m23_execution_account_v3._require_flat_demo_exposure")
 @patch("tradebot.m23_execution_account_v3.read_signed_context")
 def test_exposure_failure(self,read,flat):
    read.return_value=self.a;flat.side_effect=ValueError()
    self.assertFalse(inspect("BTCUSD",self.client,self.client)["flat_exposure_verified"])
 @patch("tradebot.m23_execution_account_v3._require_flat_demo_exposure")
 @patch("tradebot.m23_execution_account_v3.read_signed_context")
 def test_invalid_zero_exposure_types(self,read,flat):
    read.return_value=self.a
    for value in (False,0.0,"0",None):
        with self.subTest(value=value):
            flat.return_value=dict(account_flat_verified=True,open_positions=value,open_orders=0)
            self.assertFalse(inspect("BTCUSD",self.client,self.client)["flat_exposure_verified"])
            flat.return_value=dict(account_flat_verified=True,open_positions=0,open_orders=value)
            self.assertFalse(inspect("BTCUSD",self.client,self.client)["flat_exposure_verified"])
 def test_mutation_client_rejected(self):
    self.client.allow_orders=True
    self.assertEqual(inspect("BTCUSD",self.client,self.client)["stage"],"readonly_demo_required")

class LeverageEvidenceTests(unittest.TestCase):
 def setUp(self):
    self.account=dict(product={"product_id":84},configured_leverage="10")
    self.setting=dict(product_id=84,leverage=10,order_margin="0")
 def test_setting_is_not_permission(self):
    r=project_leverage(self.setting,self.account)
    self.assertTrue(r["within_existing_20x_ceiling"])
    self.assertTrue(r["blocked_order_margin_zero"])
    self.assertFalse(r["actual_order_margin_verified"])
    self.assertFalse(r["order_mutation_permission_verified"])
 def test_legacy_ceiling(self):
    r=project_leverage(dict(self.setting,leverage=25),dict(self.account,configured_leverage=25))
    self.assertFalse(r["within_existing_20x_ceiling"])
 def test_wrong_product(self):
    with self.assertRaises(ValueError):project_leverage(dict(self.setting,product_id=85),self.account)
 def test_changed_setting(self):
    with self.assertRaises(ValueError):project_leverage(dict(self.setting,leverage=5),self.account)
 def test_invalid_margin(self):
    for v in ("NaN","-1",True):
        with self.assertRaises(ValueError):project_leverage(dict(self.setting,order_margin=v),self.account)
