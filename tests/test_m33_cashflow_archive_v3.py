import unittest,sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
from contextlib import closing
from tradebot.m33_cashflow_archive_v3 import record,DAY
S="BTCUSD"
B="a"*64
def posting(**kw):
    return dict(dict(id="one",at_us=15,product_id=None,asset="USD",type="sub_account_transfer",amount="10",order_id=None,fill_id=None),**kw)
class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)/"archive.sqlite"
    def save(self,rows,observed=30):
        return record(self.p,S,B,10,20,observed,rows,84)
    def test_repeat_and_immutability(self):
        self.save([posting()])
        self.assertEqual(self.save([posting()])["query_count"],1)
        with closing(sqlite3.connect(self.p)) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute("DELETE FROM windows")
    def test_changed_posting_preserved(self):
        self.save([posting()])
        r=self.save([posting(amount="11")],31)
        self.assertEqual(r["conflicting_posting_ids"],1)
        self.assertFalse(r["execution_authorized"])
    def test_late_posting_and_missing(self):
        self.save([])
        self.save([posting()],31)
        self.save([],32)
        with closing(sqlite3.connect(self.p)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM windows").fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM posting_versions").fetchone()[0],1)
    def test_wrong_account(self):
        self.save([])
        with self.assertRaises(ValueError):record(self.p,S,"b"*64,10,20,31,[],84)
    def test_unclassified_and_window(self):
        self.assertEqual(self.save([posting(type="unknown")])["unclassified_count"],1)
        with self.assertRaises(ValueError):record(self.p,S,B,10,DAY+11,DAY+12,[],84)
        with self.assertRaises(ValueError):self.save([posting(at_us=21)],31)
