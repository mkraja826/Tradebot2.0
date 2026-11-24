import unittest,sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
from contextlib import closing
from tradebot.m31_equity_evidence_v3 import sample,store
from test_signed_account_context_v3 import Broker,NOW

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)/"evidence.sqlite"
        self.row=sample("BTCUSD",Broker(),Broker(parent=True),lambda:NOW)
    def test_persistent_duplicate(self):
        self.assertEqual(store(self.p,self.row,now=NOW),"recorded")
        self.assertEqual(store(self.p,self.row,now=NOW),"duplicate")
        with closing(sqlite3.connect(self.p)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM observations").fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):db.execute("DELETE FROM observations")
    def test_account_change(self):
        store(self.p,self.row,now=NOW)
        with self.assertRaises(ValueError):store(self.p,dict(self.row,account_binding="a"*64),now=NOW)
        with self.assertRaises(ValueError):store(self.p,dict(self.row,symbol="XAUTUSD"),now=NOW)
    def test_equity_and_timestamp(self):
        for patch in (dict(equity_usd="99"),dict(observed_us=self.row["observed_us"]+1)):
            with self.assertRaises(ValueError):store(self.p,dict(self.row,**patch),now=NOW)
    def test_wrong_label(self):
        with self.assertRaises(ValueError):sample("XAUTUSD",Broker(),Broker(parent=True),lambda:NOW)
    def test_mutation_client(self):
        c=Broker();c.allow_orders=True
        with self.assertRaises(ValueError):sample("BTCUSD",c,Broker(parent=True),lambda:NOW)
