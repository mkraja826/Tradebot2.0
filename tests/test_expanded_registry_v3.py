import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from contextlib import closing
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.commissioning_v3 import verify_events
from tradebot.strategy_registry_v3 import valid_signal_rule
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW
class ExpandedRegistryTests(unittest.TestCase):
    def test_expansion_scope(self):
        self.assertTrue(valid_signal_rule("BTCUSD","B26","15m"))
        self.assertTrue(valid_signal_rule("XAUTUSD","G30","15m"))
        for rule,frame in (("B26","1m"),("G26","15m"),("B51","15m"),("B99","15m")):
            self.assertFalse(valid_signal_rule("BTCUSD",rule,frame))
    def test_persistence_and_audit(self):
        with TemporaryDirectory() as d:
            j=OpportunityJournal(Path(d)/"events.sqlite")
            a=scan(signals=[sig("B26","15m")])
            b=scan("XAUTUSD",[sig("G30","15m")])
            self.assertIsNotNone(j.record(a,ctx()))
            self.assertIsNotNone(j.record(b,ctx("XAUTUSD")))
            self.assertIsNone(j.record(a,ctx()))
            with self.assertRaises(ValueError): j.record(scan(signals=[sig("B51","15m")]),ctx())
            with closing(j.connect()) as db:
                self.assertEqual(verify_events(db)["events"],2)
