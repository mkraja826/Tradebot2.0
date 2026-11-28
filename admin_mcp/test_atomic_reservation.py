import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from approval_ledger import initialize
from execution_journal import initialize_journal, recover_interrupted
from atomic_reservation import reserve_fixture
from operator_auth import issue_after_verification

class AtomicTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=str(Path(tmp.name)/"fixture.sqlite")
        self.db=sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        initialize(self.db)
        initialize_journal(self.db)
        self.key=b"k"*32
    def reserve(self,db,n):
        request={"id":format(n,"032x"),"action":"restart_service","target":"fixture","arguments":{},"expected_revision":"b"*40,"expires":1100}
        envelope=issue_after_verification(request,format(n,"064x"),"fixture",lambda *args:"owner",{"operators":["owner"],"audience":"fixture"},self.key,1000)
        return reserve_fixture(db,request,envelope,self.key,lambda:1000,["owner"],{"revision":"b"*40,"safe_to_restart":True})
    def test_rollback_on_target_lock(self):
        self.reserve(self.db,1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.reserve(self.db,2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM consumed").fetchone()[0],1)
    def test_duplicate(self):
        self.reserve(self.db,1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.reserve(self.db,1)
    def test_recovery_retains_lock(self):
        self.reserve(self.db,1)
        self.assertEqual(recover_interrupted(self.db,1001),1)
        self.assertEqual(self.db.execute("SELECT status FROM executions").fetchone()[0],"unknown")
        with self.assertRaises(sqlite3.IntegrityError):
            self.reserve(self.db,2)
    def test_concurrent_requests(self):
        barrier=threading.Barrier(2)
        outcomes=[]
        def worker(n):
            db=sqlite3.connect(self.path,timeout=5)
            try:
                barrier.wait(timeout=5)
                self.reserve(db,n)
                outcomes.append("reserved")
            except sqlite3.IntegrityError:
                outcomes.append("rejected")
            finally:
                db.close()
        threads=[threading.Thread(target=worker,args=(n,)) for n in (1,2)]
        for t in threads: t.start()
        for t in threads: t.join(10)
        self.assertCountEqual(outcomes,["reserved","rejected"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM consumed").fetchone()[0],1)
