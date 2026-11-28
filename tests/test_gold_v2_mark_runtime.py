import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock,patch
from recover_trading.gold_v2_mark_runtime import Loop
from recover_trading.gold_v2_hybrid import MARK_SOURCE
from test_gold_v2_mark_entry import envelope
from test_gold_v2_hybrid import NOW,ticker

class MarkLoopTests(unittest.TestCase):
    def setUp(self):
        hours = patch("recover_trading.gold_v2_mark_runtime.entry_pause_reason", return_value=None)
        self.hours = hours.start()
        self.addCleanup(hours.stop)
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name)
        self.c=Mock(enabled=True);self.c.cycle.return_value={"status":"entry_dispatch","execution_status":"acknowledged"}
        self.demo=Mock();self.ref=Mock()
        self.ref.get.return_value={"symbol":"XAUTUSD","id":1}
        self.ref.ticker.return_value=ticker(1,100)
        self.loop=Loop(self.c,self.demo,self.ref,self.root,clock=lambda:NOW)
    def tearDown(self):self.tmp.cleanup()
    @patch("recover_trading.gold_v2_mark_runtime.outstanding",return_value=[])
    @patch("recover_trading.gold_v2_mark_runtime.observe_mark")
    def test_entry_uses_explicit_mark_envelope(self,observe,owned):
        observe.return_value=envelope()
        e=self.loop.cycle()
        self.assertEqual(e["controller"]["execution_status"],"acknowledged")
        self.assertEqual(e["signal_source"],MARK_SOURCE)
        self.assertEqual(self.c.cycle.call_args.args[0],envelope())
        self.assertEqual(self.c.cycle.call_args.kwargs["reference_pid"],1)
        self.assertTrue((self.root/"mark_execution_status.json").is_file())
        self.assertEqual(self.loop.cycle()["controller"]["status"],"entry_boundary_already_observed")
        self.c.cycle.assert_called_once()
    @patch("recover_trading.gold_v2_mark_runtime.outstanding",return_value=[("cid",{})])
    @patch("recover_trading.gold_v2_mark_runtime.collect",side_effect=TimeoutError)
    @patch("recover_trading.gold_v2_mark_runtime.observe_mark",side_effect=AssertionError("production must not be read"))
    def test_owned_position_reconciles_during_feed_failure(self,observe,collect,owned):
        self.hours.return_value = "weekend"
        self.c.cycle.return_value={"status":"reconciled"}
        e=self.loop.cycle()
        self.assertEqual(e["errors"]["demo_history"],"TimeoutError")
        self.assertEqual(e["controller"]["status"],"reconciled")
        self.c.cycle.assert_called_once_with({},[],demo_as_of=NOW)
        self.ref.get.assert_not_called()
        observe.assert_not_called()
    @patch("recover_trading.gold_v2_mark_runtime.outstanding",return_value=[])
    @patch("recover_trading.gold_v2_mark_runtime.observe_mark")
    def test_no_candidate(self,observe,owned):
        r=envelope();r["mark_report"]["candidates"]=[];observe.return_value=r
        self.assertEqual(self.loop.cycle()["controller"]["status"],"no_candidate")
        self.c.cycle.assert_not_called()
    @patch("recover_trading.gold_v2_mark_runtime.outstanding",return_value=[])
    @patch("recover_trading.gold_v2_mark_runtime.observe_mark",side_effect=TimeoutError)
    def test_error_remains_retryable(self,observe,owned):
        self.assertEqual(self.loop.cycle()["errors"]["cycle"],"TimeoutError")
        self.assertIsNone(self.loop.last_entry_boundary)
        self.c.cycle.assert_not_called()

    @patch("recover_trading.gold_v2_mark_runtime.outstanding", return_value=[])
    @patch("recover_trading.gold_v2_mark_runtime.observe_mark")
    def test_closed_session_skips_scan(self, observe, owned):
        self.hours.return_value = "weekend"
        event = self.loop.cycle()
        self.assertEqual(event["controller"]["status"], "entry_scanning_paused")
        self.assertEqual(event["pause_reason"], "weekend")
        self.assertEqual(event["execution_effect"], "none")
        observe.assert_not_called()
        self.c.cycle.assert_not_called()
