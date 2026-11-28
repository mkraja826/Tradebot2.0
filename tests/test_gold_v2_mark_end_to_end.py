"""Mark controller and runtime lifecycle with synthetic public data and broker I/O."""
import unittest
from unittest.mock import patch,Mock
from recover_trading.gold_v2_mark_controller import MarkController
from recover_trading.gold_v2_mark_runtime import Loop
from recover_trading.gold_v2_controller import outstanding
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_episode import EpisodeJournal
from recover_trading.engine import Journal
from test_gold_v2_end_to_end import Exchange,B
from test_gold_v2_mark_entry import envelope
from test_gold_v2_hybrid import ticker
from contextlib import ExitStack
from tempfile import TemporaryDirectory
from pathlib import Path
from recover_trading.broker import DeltaDemo

class MarkLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(TemporaryDirectory()))
        self.exchange=Exchange();self.broker=DeltaDemo()
        self.exchange.attach(self.stack,self.broker)
        self.ref=Mock();self.ref.get.return_value={"id":1,"symbol":"XAUTUSD"}
        self.ref.ticker.side_effect=lambda s:ticker(1,self.exchange.mark,self.exchange.now)
        self.demo=Mock();self.side="LONG"
        self.stack.enter_context(patch("recover_trading.gold_v2_mark_runtime.observe_mark",side_effect=self.signal))
        self.stack.enter_context(patch("recover_trading.gold_v2_mark_runtime.collect",side_effect=lambda *a:self.bars()))
        self.reopen()
    def reopen(self):
        if hasattr(self,"orders"):self.orders.close();self.episodes.close()
        self.orders=Journal(self.root/"orders.sqlite")
        self.episodes=EpisodeJournal(self.root/"episodes.sqlite")
        self.controller=MarkController(self.broker,self.orders,self.episodes,expected_account="123",
                               allocation_fraction=.1,enabled=True,clock=lambda:self.exchange.now)
        self.loop=Loop(self.controller,self.demo,self.ref,self.root,clock=lambda:self.exchange.now)
    def tearDown(self):self.orders.close();self.episodes.close()
    def signal(self,demo,ref,stamp):
        r=envelope(self.side);r["as_of"]=stamp;r["mark_report"]["as_of"]=stamp
        r["mark_report"]["candidates"][0]["reference_close"]=self.exchange.mark
        return r
    def bars(self):
        end=self.exchange.now//300*300
        out=[]
        for t in range(end-249*300,end+1,300):
            c=100 if t<B+600 else (102 if t<B+900 else 103.5)
            out.append(Bar(t,c,c+1,c-1,c,0))
        return out
    def cycle(self):return self.loop.cycle()["controller"]
    def test_long_lifecycle(self):
        e=self.exchange
        self.assertEqual(self.cycle()["post_entry_observation"],"owned_open")
        self.assertEqual(e.qty,2)
        seed=outstanding(self.episodes)[0][1]
        self.assertEqual(seed["signal_provenance"]["signal_source"],"corroborated_production_mark")
        e.tick(B+620,102)
        self.assertEqual(self.cycle()["management_status"],"verified")
        self.assertEqual(e.mutations,["entry","amend"])
        e.tick(B+920,103.5)
        self.assertEqual(self.cycle()["management_status"],"verified")
        self.assertEqual(e.qty,1)
        self.reopen()
        e.tick(B+940,106);e.trigger("take_profit_order")
        self.assertEqual(self.cycle()["status"],"closed")
        self.assertFalse(outstanding(self.episodes))
        e.tick(B+1220,100)
        self.assertEqual(self.cycle()["execution_status"],"acknowledged")
        self.assertEqual(e.mutations.count("entry"),2)
    def test_short_lost_acknowledgment(self):
        e=self.exchange;self.side="SHORT";e.unknown_entry=True
        self.assertEqual(self.cycle()["execution_status"],"unknown")
        self.assertEqual(e.qty,-2)
        self.reopen();e.tick(B+40,100)
        self.cycle()
        self.assertFalse(self.orders.unresolved())
        self.assertEqual(e.mutations,["entry"])
        e.tick(B+60,94);e.trigger("take_profit_order")
        self.assertEqual(self.cycle()["status"],"closed")
        self.assertFalse(outstanding(self.episodes))
