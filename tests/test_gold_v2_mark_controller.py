import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from recover_trading.broker import DeltaDemo
from recover_trading.engine import Journal
from recover_trading.gold_v2_episode import EpisodeJournal,client_id
from recover_trading.gold_v2_controller import outstanding
from recover_trading.gold_v2_mark_controller import MarkController,management_report,MANAGEMENT_SOURCE
from recover_trading.gold_v2_mark_entry import VERSION,MODEL,MARK_SOURCE
from test_gold_v2_mark_entry import envelope
from test_gold_v2_hybrid import NOW,ticker

class MarkControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();root=Path(self.tmp.name)
        self.orders=Journal(root/"orders.sqlite")
        self.episodes=EpisodeJournal(root/"episodes.sqlite")
        self.broker=DeltaDemo()
    def tearDown(self):
        self.orders.close();self.episodes.close();self.tmp.cleanup()
    def controller(self,enabled=True):
        return MarkController(self.broker,self.orders,self.episodes,expected_account="123",
                              allocation_fraction=.1,enabled=enabled,clock=lambda:NOW)
    def test_disabled_no_network(self):
        with patch.object(self.broker,"wallet",side_effect=AssertionError("network")):
            self.assertEqual(self.controller(False).cycle(envelope())["status"],"disabled")
    def test_mark_dispatch_persists_provenance(self):
        c=self.controller()
        result={"status":"proposed","version":VERSION,"model_version":MODEL,"signal_source":MARK_SOURCE,
                "entry_family":"mark_breakout_retest","research_quote_pair":{"demo_product_id":42},
                "signal_atr":"2.2","proposal":{"side":"buy","size":4,"stop_loss":106.7,"take_profit":116.6}}
        def dispatch(*args,**kwargs):
            seed=outstanding(self.episodes)[0][1]
            self.assertEqual(seed["signal_atr"],"2.2")
            self.assertEqual(seed["signal_provenance"]["signal_source"],MARK_SOURCE)
            self.assertEqual(seed["signal_provenance"]["entry_family"],"mark_breakout_retest")
            return {"status":"unknown"}
        with patch("recover_trading.gold_v2_mark_controller.verify_account",return_value="123"), \
             patch("recover_trading.gold_v2_mark_controller.prepare_mark",return_value=(result,{"product":{"id":42}})), \
             patch.object(c.entry,"execute",side_effect=dispatch) as submit:
            self.assertEqual(c.entry_cycle(envelope(),ref_ticker=ticker(1,100),reference_pid=1)["execution_status"],"unknown")
            self.assertEqual(c.entry_cycle(envelope())["status"],"unresolved_episode_or_order")
            submit.assert_called_once()
    def test_wrong_source_not_dispatched(self):
        c=self.controller()
        with patch("recover_trading.gold_v2_mark_controller.verify_account",return_value="123"), \
             patch.object(c.entry,"execute") as submit:
            self.assertEqual(c.cycle({"symbol":"BTCUSD"})["status"],"wrong_mark_source")
            submit.assert_not_called()
    def test_management_even_without_valid_market_history(self):
        c=self.controller()
        self.episodes.reserve({"symbol":"XAUTUSD","client_id":client_id(3600000),"signal_boundary":3600000,
                               "flat_verified":True,"signal_provenance":{"signal_source":MARK_SOURCE}})
        with patch.object(c,"manage_cycle",return_value={"status":"reconciled"}) as manage, \
             patch.object(c.entry,"execute") as submit:
            self.assertEqual(c.cycle({},[])["status"],"reconciled")
            report=manage.call_args.args[0]
            self.assertEqual(report["signal_source"],MANAGEMENT_SOURCE)
            self.assertEqual(report["status"],"data_unusable")
            submit.assert_not_called()
    def test_unowned_legacy_episode_not_adopted(self):
        c=self.controller()
        self.episodes.reserve({"symbol":"XAUTUSD","client_id":client_id(3600000),"signal_boundary":3600000,"flat_verified":True})
        with patch.object(c,"manage_cycle") as manage:
            self.assertEqual(c.cycle(envelope())["status"],"wrong_episode_source")
            manage.assert_not_called()
