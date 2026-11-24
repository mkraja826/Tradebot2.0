"""Owner declaration may substitute margin evidence in BTC DEMO only."""
import unittest
from unittest.mock import patch
from tradebot.delta import DEMO_API
from tradebot.fire_account_guard import require_flat_demo_account_operator_declared as gated, AccountExposureRejected as Blocked
from tradebot.fire_execution import FireDemoController
from tradebot.btc_supervised_execution import SupervisedBTCController

class Demo:
    base_url=DEMO_API
    allow_orders=True

def owner():
    return {"status":"owner_declared_not_broker_verified",
            "account":"main","declared_mode":"isolated",
            "broker_margin_verified":False,"trade_authorized":False}

class OwnerModeTests(unittest.TestCase):
    def test_live_exposure_still_required(self):
        with patch("tradebot.operator_account_mode.read_manual_mode",
                   return_value=owner()) as setting, patch(
                "tradebot.fire_account_guard._require_flat_demo_exposure",
                return_value={"account_flat_verified":True}) as flat:
            self.assertTrue(gated(Demo(),selected_symbol="BTCUSD",
                                  selected_product_id=27)["account_flat_verified"])
            self.assertTrue(setting.call_args.kwargs["allow_order_client"])
            self.assertEqual(flat.call_args.kwargs["selected_product_id"],27)
    def test_missing_stale_or_false_broker_proof_fails_closed(self):
        for declaration in ({"status":"not_configured"},
                            {**owner(),"status":"owner_declaration_expired"},
                            {**owner(),"broker_margin_verified":True}):
            with patch("tradebot.operator_account_mode.read_manual_mode",
                       return_value=declaration),patch(
                    "tradebot.fire_account_guard._require_flat_demo_exposure") as flat:
                with self.assertRaises(Blocked):
                    gated(Demo(),selected_symbol="BTCUSD",selected_product_id=27)
                flat.assert_not_called()
    def test_gold_and_live_rejected_without_owner_read(self):
        for symbol,endpoint in (("XAUTUSD",DEMO_API),
                                ("BTCUSD","https://api.india.delta.exchange")):
            c=Demo();c.base_url=endpoint
            with patch("tradebot.operator_account_mode.read_manual_mode") as read:
                with self.assertRaises(Blocked):
                    gated(c,selected_symbol=symbol,selected_product_id=27)
                read.assert_not_called()
    def test_any_position_blocks_even_with_owner_mode(self):
        with patch("tradebot.operator_account_mode.read_manual_mode",
                   return_value=owner()),patch(
                "tradebot.fire_account_guard._require_flat_demo_exposure",
                side_effect=Blocked("Account has open exposure")):
            with self.assertRaisesRegex(Blocked,"open exposure"):
                gated(Demo(),selected_symbol="BTCUSD",selected_product_id=27)
    def test_normal_fire_stays_strict(self):
        with patch("tradebot.fire_execution.require_flat_demo_account",
                   side_effect=Blocked("signed proof absent")) as strict:
            with self.assertRaises(Blocked):
                FireDemoController._require_account_flat(
                    type("C",(),{"symbol":"BTCUSD"})(),Demo(),27)
            strict.assert_called_once()
    def test_supervised_controller_routes_owner_mode(self):
        with patch("tradebot.btc_supervised_execution.require_flat_demo_account_operator_declared",
                   return_value={"account_flat_verified":True}) as fn:
            self.assertTrue(SupervisedBTCController._require_account_flat(
                type("C",(),{"symbol":"BTCUSD"})(),Demo(),27)["account_flat_verified"])
            fn.assert_called_once()
