import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch,Mock
from recover_trading.broker import DeltaDemo
from recover_trading.engine import Journal
from recover_trading.gold_v2_episode import EpisodeJournal
from recover_trading.gold_v2_controller import Controller,outstanding,stage_management,VERSION
from recover_trading.management_shadow import VERSION as SHADOW_VERSION,ManagementShadow

NOW=3600020
def report():
    return {"symbol":"XAUTUSD","status":"observed","as_of":3600000,
            "candidates":[{"family":"trend_pullback","direction":"LONG","atr":2}]}
def packet():
    c={"version":SHADOW_VERSION,"symbol":"XAUTUSD","as_of":NOW,"position_observed":NOW,
       "position":{"direction":"long","size":4,"entry_price":"100","mark_price":"102",
                   "bracket_state":"matching_legs_observed","legs":[]},
       "product":{"id":42,"tick_size":"0.1"}}
    return {"symbol":"XAUTUSD","status":"proposal_prepared","context":c,
            "proposal":{"symbol":"XAUTUSD","action":"reduce","contracts":2,"reason":"fixture"},
            "entry_client_id":"fixture","bar_boundary":3600000}

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.orders=Journal(root/"orders.sqlite")
        self.episodes=EpisodeJournal(root/"episode.sqlite")
        self.broker=DeltaDemo()
    def tearDown(self):
        self.orders.close();self.episodes.close();self.temp.cleanup()
    def controller(self,enabled=False):
        return Controller(self.broker,self.orders,self.episodes,expected_account="123",
                          allocation_fraction=.1,enabled=enabled,clock=lambda:NOW)
    def test_disabled_no_network(self):
        with patch.object(self.broker,"wallet",side_effect=AssertionError("network")):
            self.assertEqual(self.controller().cycle(report())["status"],"disabled")
    def test_stage_idempotency(self):
        ManagementShadow(self.orders.db)
        ident=stage_management(self.orders.db,packet(),now=NOW)
        self.assertIsNotNone(ident)
        self.assertIsNone(stage_management(self.orders.db,packet(),now=NOW))
        row=self.orders.db.execute("SELECT model,status FROM management_shadow").fetchone()
        self.assertEqual(row,(VERSION,"proposed"))
    def test_stale_stage(self):
        ManagementShadow(self.orders.db)
        with self.assertRaises(ValueError):stage_management(self.orders.db,packet(),now=NOW+300)
    def test_wrong_symbol(self):
        p=packet();p["symbol"]="BTCUSD"
        with self.assertRaises(ValueError):stage_management(self.orders.db,p,now=NOW)
    def test_durable_seed_before_dispatch(self):
        c=self.controller(True)
        decision={"status":"proposed","proposal":{"side":"buy","size":4,"stop_loss":98,"take_profit":106}}
        account={"product":{"id":42,"symbol":"XAUTUSD"}}
        def dispatch(*a,**k):
            self.assertEqual(len(outstanding(self.episodes)),1)
            return {"status":"acknowledged"}
        with patch("recover_trading.gold_v2_controller.verify_account",return_value="123"), \
             patch("recover_trading.gold_v2_controller.prepare",return_value=(decision,account)), \
             patch.object(c.entry,"execute",side_effect=dispatch), \
             patch.object(c,"collect",side_effect=RuntimeError("fixture")) as collect:
            response=c.entry_cycle(report())
            self.assertEqual(response["execution_status"],"acknowledged")
            self.assertEqual(response["post_entry_observation"],"observation_failed")
            collect.assert_called_once()
            self.assertEqual(c.entry_cycle(report())["status"],"unresolved_episode_or_order")
    def test_failed_dispatch_retains_seed(self):
        c=self.controller(True)
        decision={"status":"proposed","proposal":{"side":"buy","size":4,"stop_loss":98,"take_profit":106}}
        account={"product":{"id":42,"symbol":"XAUTUSD"}}
        with patch("recover_trading.gold_v2_controller.verify_account",return_value="123"), \
             patch("recover_trading.gold_v2_controller.prepare",return_value=(decision,account)), \
             patch.object(c.entry,"execute",side_effect=RuntimeError("fixture")):
            with self.assertRaises(RuntimeError):c.entry_cycle(report())
            self.assertEqual(len(outstanding(self.episodes)),1)
    def test_account_mismatch_no_dispatch(self):
        c=self.controller(True)
        with patch.object(self.broker,"wallet",return_value={"result":[{"asset_symbol":"USD","user_id":"456"}]}), \
             patch.object(c.entry,"execute") as submit:
            with self.assertRaises(ValueError):c.entry_cycle(report())
            submit.assert_not_called()


    def test_terminal_bar_not_reused(self):
        from recover_trading.gold_v2_episode import client_id
        from recover_trading.gold_v2_recovery import persist_no_submission
        c=self.controller(True)
        cid=client_id(3600000)
        seed={"symbol":"XAUTUSD","client_id":cid,"signal_boundary":3600000,"flat_verified":True}
        self.episodes.reserve(seed)
        persist_no_submission(self.episodes,seed,{"status":"terminal_no_submission"},now=NOW)
        decision={"status":"proposed","proposal":{"side":"buy","size":4,"stop_loss":98,"take_profit":106}}
        account={"product":{"id":42,"symbol":"XAUTUSD"}}
        with patch("recover_trading.gold_v2_controller.verify_account",return_value="123"), \
             patch("recover_trading.gold_v2_controller.prepare",return_value=(decision,account)), \
             patch.object(c.entry,"execute") as submit:
            self.assertEqual(c.entry_cycle(report())["status"],"entry_bar_already_reserved")
            submit.assert_not_called()
