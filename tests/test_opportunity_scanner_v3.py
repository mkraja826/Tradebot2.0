import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from tradebot.opportunity_journal_v3 import OpportunityJournal,digest
from tradebot.opportunity_scanner_v3 import tick,context_for
from tradebot.market_data_v3 import FRAMES

NOW=1800000000
def sig(id="B01",frame="5m",direction="LONG",stamp=NOW):
    return dict(id=id,frame=frame,direction=direction,closed_at=stamp//FRAMES[frame]*FRAMES[frame])
def scan(symbol="BTCUSD",signals=None,stamp=NOW):
    return dict(symbol=symbol,as_of=stamp,signals=[sig()] if signals is None else signals,ai_dispatched=False,orders_submitted=0)
def ctx(symbol="BTCUSD",stamp=NOW):
    return dict(symbol=symbol,as_of=stamp)
class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.path=self.root/"events.sqlite"
        self.j=OpportunityJournal(self.path)
    def test_one_signal_restart_and_next_candle(self):
        e=self.j.record(scan(),ctx())
        self.assertEqual(len(e["new_signals"]),1)
        self.assertEqual(e["context_sha256"],digest(ctx()))
        self.assertFalse(e["execution_authorized"])
        self.assertIsNone(OpportunityJournal(self.path).record(scan(),ctx()))
        n=NOW+300
        self.assertIsNotNone(self.j.record(scan(signals=[sig(stamp=n)],stamp=n),ctx(stamp=n)))
        self.assertEqual(self.j.counts()["BTCUSD"],dict(events=2,signals=2))
    def test_consolidation_conflict_and_new_signal(self):
        a=sig(); b=sig("B02","1h","SHORT")
        e=self.j.record(scan(signals=[a,b,a]),ctx())
        self.assertEqual(len(e["new_signals"]),2); self.assertTrue(e["conflicting_directions"])
        c=sig("B03")
        e=self.j.record(scan(signals=[a,b,c]),ctx())
        self.assertEqual(e["new_signals"],[c]); self.assertEqual(len(e["all_signals"]),3)
    def test_market_isolation(self):
        self.j.record(scan(),ctx())
        e=self.j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))
        self.assertEqual(e["model_if_enabled"],"DeepSeek")
        self.assertEqual(self.j.counts()["XAUTUSD"]["events"],1)
        with self.assertRaises(ValueError): self.j.record(scan("XAUTUSD"),ctx("XAUTUSD"))
        with self.assertRaises(ValueError): self.j.record(scan(),ctx("XAUTUSD"))
    def test_stale_and_empty_and_concurrent(self):
        self.assertIsNone(self.j.record(scan(signals=[]),ctx()))
        with self.assertRaises(ValueError): self.j.record(scan(signals=[sig(stamp=NOW-300)]),ctx())
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(lambda _:self.j.record(scan(),ctx()),range(2)))
        self.assertEqual(sum(x is not None for x in result),1)
    def test_stale_collector_and_external_isolation(self):
        self.assertEqual(tick(self.root,now=NOW)["status"],"collector_unavailable")
        x=context_for("BTCUSD",NOW,{},{"btc_spot":{"status":"ready","observed_at":NOW-1},"yields":{"status":"ready","observed_at":NOW}},NOW)
        self.assertEqual(set(x["external"]),{"btc_spot"})
        self.assertEqual(x["external"]["btc_spot"]["status"],"ready")
