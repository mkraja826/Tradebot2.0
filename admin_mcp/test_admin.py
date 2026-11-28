"""Tests for the standalone admin tool contract (no real host mutation)."""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("tb2_admin",Path(__file__).with_name("tb2_admin.py"))
admin=importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)

class AdminTests(unittest.TestCase):
    def test_registered_twenty_four(self):
        class Fake:
            names=[]
            def tool(self):
                def register(f):
                    self.names.append(f.__name__)
                    return f
                return register
        s=Fake()
        admin.register(s)
        self.assertEqual(len(s.names),24)
        self.assertEqual(len(set(s.names)),24)

    def test_paths(self):
        self.assertEqual(admin.source_path("recover_trading/engine.py"),"recover_trading/engine.py")
        for p in ("/etc/passwd","../engine.py",".env","config/token.py","config/private.py"):
            with self.assertRaises(ValueError):admin.source_path(p)

    def test_stage_only(self):
        with tempfile.TemporaryDirectory() as d:
            q=Path(d)
            with patch.object(admin,"QUEUE",q):
                with patch.object(admin,"command",side_effect=AssertionError("unexpected command")):
                    result=admin.disk_cleanup()
                    self.assertEqual(result["execution_effect"],"none")
                    self.assertEqual(result["status"],"pending_local_approval")
                    self.assertTrue((q/(result["request_id"]+".json")).exists())

    def test_no_arbitrary_service(self):
        with patch.object(admin,"SERVICES",("example.service",)):
            with self.assertRaises(ValueError):admin.restart_service("sshd.service")

    def test_snapshot_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"market.sqlite"
            with sqlite3.connect(p) as db:db.execute("CREATE TABLE samples(stamp INTEGER)")
            with patch.object(admin,"SNAPSHOTS",Path(d)):
                self.assertEqual(admin.database_inspect("market.sqlite")["objects"],[("samples","table")])
                with self.assertRaises(ValueError):admin.database_inspect("../market.sqlite")

if __name__=="__main__":unittest.main()
