import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
from recover_trading.service import MarketService
from test_recover_service import Provider, scan
from test_recover_execution import Fake


class CycleTests(unittest.TestCase):
    def service(self, directory, events, symbol="BTCUSD"):
        return MarketService(symbol,directory,model="fixture",provider=Provider(),broker=Fake(),
            scan=scan,output=events.append,manage_demo=True,
            lr_v4b_events="/fixture/events.sqlite",lr_v4b_demo=True)

    def test_requires_demo_management(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                MarketService("BTCUSD",directory,lr_v4b_demo=True)

    def test_owned_cycle_excludes_legacy_ai_and_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[]
            controller=MagicMock()
            controller.outstanding.return_value=[("cid","acknowledged","acknowledged")]
            controller.manage.return_value={"status":"maintain","owned":True,"attempted":False}
            with patch("recover_trading.service.Controller",return_value=controller), \
                 patch("recover_trading.service.evaluate_and_execute") as legacy, \
                 patch("recover_trading.service.ManagementShadow.capture") as capture:
                service=self.service(directory,events)
                service.run(threading.Event(),1,once=True)
            self.assertEqual(events[0]["status"],"lr_v4b_management_cycle")
            self.assertTrue(events[0]["lr_v4b_owns_cycle"])
            capture.assert_not_called()
            legacy.assert_not_called()
            controller.enter.assert_not_called()
            controller.manage.assert_called_once()

    def test_flat_routes_to_lr_entry_or_existing_strategy(self):
        for response in (None,{"status":"lr_signal_expired","ai_calls":0}):
            with tempfile.TemporaryDirectory() as directory:
                events=[]
                controller=MagicMock()
                controller.outstanding.return_value=[]
                controller.enter.return_value=response
                with patch("recover_trading.service.Controller",return_value=controller), \
                     patch("recover_trading.service.Lifecycle.refresh",return_value={"positions":[],"active_orders":[],"active_orders_complete":True}), \
                     patch("recover_trading.service.BracketRepair.cycle",return_value={}), \
                     patch("recover_trading.service.ManagementShadow.capture",return_value={}), \
                     patch("recover_trading.service.evaluate_and_execute",return_value={"status":"legacy_fixture","ai_calls":0}) as legacy:
                    service=self.service(directory,events)
                    service.run(threading.Event(),1,once=True)
                controller.enter.assert_called_once()
                self.assertEqual(legacy.call_count,int(response is None))
                self.assertEqual(events[0]["status"],"legacy_fixture" if response is None else "lr_signal_expired")

    def test_gold_does_not_instantiate_lr_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[]
            with patch("recover_trading.service.Controller") as controller:
                service=self.service(directory,events,"XAUTUSD")
                service.open()
                try:
                    self.assertFalse(service.lr_v4b_demo)
                    self.assertIsNone(service.lr_controller)
                finally:
                    service.close()
            controller.assert_not_called()
