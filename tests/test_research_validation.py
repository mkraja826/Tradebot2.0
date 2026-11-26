import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from recover_trading.research_validation import audit_rows,copy_db,run

class ResearchValidationTests(unittest.TestCase):
    def test_missing_data_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            r=run(p/"demo",p/"learning",1,2,3)
            self.assertEqual(r["status"],"review_required")
            self.assertFalse(r["live_activation_ready"])
            self.assertFalse(r["profitability_improvement_validated"])
            self.assertFalse((p/"demo").exists())
    def test_wal_backup_and_no_source_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/"original.sqlite";dest=p/"copy.sqlite"
            with closing(sqlite3.connect(source)) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE t(v INTEGER)")
                db.execute("INSERT INTO t VALUES (42)")
                db.commit()
                self.assertEqual(copy_db(source,dest)["status"],"copied")
                with closing(sqlite3.connect(dest)) as other:
                    self.assertEqual(other.execute("SELECT v FROM t").fetchone(),(42,))
                self.assertEqual(db.execute("SELECT v FROM t").fetchone(),(42,))
    def test_mismatch_duplicate_missing(self):
        expected={("a","t"):{"net_before_funding":"1"},("b","t"):{"net_before_funding":"2"}}
        rows=[{"decision_id":"a","closed":"t","net":"3"},{"decision_id":"a","closed":"t","net":"1"}]
        r=audit_rows(expected,rows,lambda x:x["net"])
        self.assertEqual(r["issues"]["pnl_mismatch"],1)
        self.assertEqual(r["issues"]["duplicate"],1)
        self.assertEqual(r["issues"]["missing_episode"],1)
    def test_matching_values(self):
        e={("a","t"):{"net_before_funding":"1.00"}}
        self.assertEqual(audit_rows(e,[{"decision_id":"a","closed":"t","net":"1"}],lambda x:x["net"])["status"],"consistent")
        self.assertEqual(audit_rows({},[],lambda x:x)["status"],"no_sample")
    def test_invalid_cutoff(self):
        with self.assertRaises(ValueError):run("x","y",3,2,1)
