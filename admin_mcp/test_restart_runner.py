import sqlite3
import unittest
from execution_journal import initialize_journal, reserve
from restart_runner import run_fixture

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        initialize_journal(self.db)
        self.rid="a"*32
        reserve(self.db,self.rid,"b"*64,"fixture",1000)
    def run_case(self,simulate):
        return run_fixture(self.db,self.rid,lambda:1001,simulate)
    def status(self):
        return self.db.execute("SELECT status FROM executions").fetchone()[0]
    def test_success(self):
        def simulate(argv,**kwargs):
            return {"returncode":0,"stdout":"ActiveState=active\nSubState=running\nResult=success\n"}
        self.assertEqual(self.run_case(simulate)["status"],"succeeded")
        with self.assertRaises(ValueError): self.run_case(simulate)
    def test_timeout(self):
        def simulate(*args,**kwargs): raise TimeoutError()
        with self.assertRaises(TimeoutError): self.run_case(simulate)
        self.assertEqual(self.status(),"unknown")
        with self.assertRaises(ValueError): self.run_case(simulate)
    def test_failed_verification(self):
        self.assertEqual(self.run_case(lambda *a,**k:{"returncode":0,"stdout":"inactive"})["status"],"unknown")
    def test_competing_claim(self):
        def simulate(*args,**kwargs):
            with self.assertRaises(ValueError):
                self.run_case(lambda *a,**k:self.fail("duplicate execution"))
            return {"returncode":1}
        self.assertEqual(self.run_case(simulate)["status"],"unknown")
