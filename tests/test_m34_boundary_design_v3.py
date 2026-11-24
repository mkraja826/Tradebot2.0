import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from tradebot.m23_execution_adapter_v3 import exercise
from tradebot.execution_preview_ledger_v3 import PreviewLedger
from test_m23_execution_adapter_v3 import spec,NOW

class BoundaryDesignTests(unittest.TestCase):
    @patch("socket.socket",side_effect=AssertionError("offline network prohibited"))
    def test_offline_adapter_matrix(self,network):
        for s in ("BTCUSD","XAUTUSD"):
            r=exercise(s,spec(s),NOW)
            self.assertEqual(r["WAIT_MARKET"],"wait_no_order")
            self.assertEqual(r["LONG_MARKET"],"existing_validator_passed_fixture")
            self.assertEqual(r["SHORT_MARKET"],"existing_validator_passed_fixture")
            self.assertEqual(r["LONG_LIMIT"],"limit_execution_not_supported")
            self.assertEqual(r["SHORT_LIMIT"],"limit_execution_not_supported")
        network.assert_not_called()
    @patch("socket.socket",side_effect=AssertionError("offline network prohibited"))
    def test_reservation_unknown_never_becomes_new_reservation(self,network):
        with TemporaryDirectory() as d:
            path=Path(d)/"fixture.sqlite"
            p=dict(mode="synthetic_execution_preview",execution_authorized=False,
                   event_id="synthetic-intent",action="LONG",entry={"fixture":True})
            self.assertEqual(PreviewLedger(path).reserve(p,now=NOW),"reserved")
            self.assertEqual(PreviewLedger(path).recover(now=NOW+121),1)
            self.assertEqual(PreviewLedger(path).reserve(p,now=NOW+122),"already_reserved")
            with self.assertRaises(ValueError):
                PreviewLedger(path).reserve(dict(p,action="SHORT"),now=NOW+123)
        network.assert_not_called()
