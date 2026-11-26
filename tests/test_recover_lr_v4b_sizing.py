import tempfile
import unittest
from unittest.mock import Mock,patch
from recover_trading.engine import Journal
from recover_trading.execution import DemoExecutor
from recover_trading.management_executor import ManagementExecutor
from recover_trading.lr_v4b_controller import Controller
from test_recover_execution import Fake


class SizingTests(unittest.TestCase):
    def setUp(self):
        self.j=Journal(":memory:")
        self.addCleanup(self.j.close)
        self.b=Fake()
        self.p=Mock()
        self.c=Controller(DemoExecutor(self.b,self.j),ManagementExecutor(self.b,self.j),self.p,"fixture","/unused")
        self.signal={"version":"lr-v4b","symbol":"BTCUSD","signal_time":600,"burst_time":540,"side":"buy","initial_stop":95}
        self.shadow={"status":"observed","recent_signal":self.signal}
        self.flat={"positions":[],"active_orders":[],"active_orders_complete":True}
    def test_sizing_once_even_if_no_trade(self):
        self.p._propose.return_value={"action":"no_trade"}
        with patch("recover_trading.lr_v4b_controller.time.time",return_value=601):
            with patch("recover_trading.lr_v4b_controller.submit",return_value={"status":"no_trade"}) as submit:
                self.assertEqual(self.c.enter(self.shadow,self.flat)["execution"]["status"],"no_trade")
                self.assertEqual(self.c.enter(self.shadow,self.flat)["status"],"lr_sizing_already_requested")
                submit.assert_called_once()
        self.p._propose.assert_called_once()
    def test_expired_before_sizing(self):
        with patch("recover_trading.lr_v4b_controller.time.time",return_value=660):
            self.assertEqual(self.c.enter(self.shadow,self.flat)["status"],"lr_signal_expired")
        self.p._propose.assert_not_called()
    def test_unverified_archive_no_sizing(self):
        with patch("recover_trading.lr_v4b_controller.time.time",return_value=601):
            self.assertEqual(self.c.enter({**self.shadow,"status":"unavailable"},self.flat)["status"],"lr_signal_unverified")
        self.p._propose.assert_not_called()
