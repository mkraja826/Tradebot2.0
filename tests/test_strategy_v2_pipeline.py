"""Strategy V2 durable signal journaling and safe shadow pipeline tests."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import os
import unittest
from unittest.mock import patch

from tradebot.delta import DEMO_API
from tradebot.signal_ai_router import build_ai_signal_event
from tradebot.strategy_v2.journal import SignalJournal
from tradebot.strategy_v2.pipeline import inspect_symbol, run_shadow_once
from test_multi_strategy_signals import candles
from test_signal_ai_router import scan


def ready_event(symbol="BTCUSD"):
    return build_ai_signal_event(scan(symbol))


class FakeFeed:
    base_url=DEMO_API
    allow_orders=False
    def __init__(self, broken=None):
        self.broken=broken
        self.calls=[]
    def candles(self, *, symbol, resolution, start, end):
        self.calls.append((symbol,resolution))
        if symbol == self.broken:
            raise RuntimeError("feed offline")
        return candles(250)


class SignalJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=self.root/"observations.sqlite"

    def test_first_observation_persisted_and_replay_is_idempotent(self):
        journal=SignalJournal(self.db)
        event=ready_event()
        self.assertEqual(journal.observe(event)["status"],"new_signal_observed")
        self.assertEqual(journal.observe(event)["status"],"duplicate_signal_observation")
        self.assertEqual(journal.count(),1)
        self.assertEqual(SignalJournal(self.db).count(),1)
        import sqlite3
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT direction_hint FROM signal_observations"
            ).fetchone()[0], "LONG")

    def test_both_market_events_are_independent(self):
        journal=SignalJournal(self.db)
        self.assertEqual(journal.observe(ready_event("BTCUSD"))["status"],
                         "new_signal_observed")
        self.assertEqual(journal.observe(ready_event("XAUTUSD"))["status"],
                         "new_signal_observed")
        self.assertEqual(journal.count(),2)

    def test_modified_closed_candle_evidence_never_requeues(self):
        journal=SignalJournal(self.db)
        event=ready_event()
        journal.observe(event)
        changed=copy.deepcopy(event)
        changed["signals"][0]["score"]=75
        self.assertEqual(journal.observe(changed)["status"],
                         "signal_changed_on_completed_candle")
        self.assertEqual(journal.count(),1)

    def test_concurrent_duplicate_observation_has_single_winner(self):
        SignalJournal(self.db)
        event=ready_event()
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes=list(pool.map(lambda _:
                SignalJournal(self.db).observe(event)["status"],range(12)))
        self.assertEqual(outcomes.count("new_signal_observed"),1)
        self.assertEqual(outcomes.count("duplicate_signal_observation"),11)
        self.assertEqual(SignalJournal(self.db).count(),1)

    def test_invalid_events_rejected(self):
        journal=SignalJournal(self.db)
        for bad_field,value in (("execution_authorized",True),
                                ("dispatch_ai",False),("symbol","BTCUSDT"),
                                ("event_id","invalid"),("model","unknown")):
            event=copy.deepcopy(ready_event())
            event[bad_field]=value
            with self.subTest(field=bad_field):
                with self.assertRaises(ValueError):
                    journal.observe(event)
        self.assertEqual(journal.count(),0)

    def test_symlink_and_unprivate_journal_paths_refused(self):
        outside=self.root/"outside.sqlite"
        outside.write_text("")
        link=self.root/"link.sqlite"
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            SignalJournal(link)
        bad=self.root/"bad"
        bad.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            SignalJournal(bad/"journal.sqlite")

    def test_private_file_mode(self):
        SignalJournal(self.db)
        self.assertEqual(self.db.stat().st_mode & 0o777,0o600)


class ShadowPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"private"

    def test_reads_both_markets_without_ai_or_orders(self):
        feed=FakeFeed()
        now=candles(250)[-1]["time"]+300
        first=run_shadow_once(client=feed,now=now,journal_dir=self.root)
        self.assertEqual(first["mode"],"STRATEGY_V2_SHADOW")
        self.assertEqual(first["ai_requests"],0)
        self.assertEqual(first["broker_mutations"],0)
        self.assertEqual(len(feed.calls),2)
        self.assertTrue(all(not row["ai_dispatched"]
                            and not row["execution_authorized"]
                            for row in first["markets"]))

    def test_broken_market_does_not_break_other_market(self):
        feed=FakeFeed(broken="BTCUSD")
        result=run_shadow_once(client=feed,
                    now=candles(250)[-1]["time"]+300,
                    journal_dir=self.root)
        self.assertEqual(result["markets"][0]["status"],"shadow_scan_unavailable")
        self.assertNotEqual(result["markets"][1]["status"],"shadow_scan_unavailable")

    def test_qualifying_candle_observed_once_across_process_cycles(self):
        feed=FakeFeed()
        now=candles(250)[-1]["time"]+300
        event=scan("BTCUSD")
        time_key=candles(250)[-1]["time"]
        event["candle_time"]=time_key
        entry=event["signals"][0]
        entry["candle_time"]=time_key
        from hashlib import sha256
        identity=f'BTCUSD:{time_key}:{entry["strategy_id"]}:LONG'
        entry["signal_id"]=sha256(identity.encode()).hexdigest()[:20]
        def scan_for_market(_,symbol,*,as_of):
            if symbol=="BTCUSD":
                return event
            return scan("XAUTUSD",signals=[])
        with patch("tradebot.strategy_v2.pipeline.scan_completed_5m",
                   side_effect=scan_for_market):
            first=run_shadow_once(client=feed,now=now,journal_dir=self.root)
            second=run_shadow_once(client=feed,now=now,journal_dir=self.root)
        self.assertEqual(first["events_recorded"],1)
        self.assertEqual(second["events_recorded"],1)
        self.assertTrue(first["markets"][0]["ai_candidate_recorded"])
        self.assertEqual(second["markets"][0]["status"],
                         "duplicate_signal_observation")
        self.assertFalse(second["markets"][0]["ai_candidate_recorded"])
        self.assertEqual(first["ai_requests"],second["ai_requests"])
        self.assertEqual(first["broker_mutations"],0)

    def test_order_capable_client_refused_before_market_call(self):
        feed=FakeFeed()
        feed.allow_orders=True
        with TemporaryDirectory() as root:
            journal=SignalJournal(Path(root)/"signals.sqlite")
            with self.assertRaises(ValueError):
                inspect_symbol(feed,"BTCUSD",as_of=1800075000,journal=journal)
        self.assertFalse(feed.calls)

