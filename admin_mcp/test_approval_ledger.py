import sqlite3
import tempfile
import unittest
from pathlib import Path
from approval_ledger import initialize, consume

class LedgerTests(unittest.TestCase):
    def test_persistent_replay_rejection(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"ledger.sqlite"
            claims={"nonce":"a"*32,"digest":"b"*64,"issued":100,"expires":200}
            with sqlite3.connect(path) as db:
                initialize(db)
                consume(db,claims,150)
            db.close()
            with sqlite3.connect(path) as db:
                with self.assertRaises(ValueError):
                    consume(db,claims,151)
                with self.assertRaises(ValueError):
                    consume(db,dict(claims,nonce="c"*32),151)
                with self.assertRaises(ValueError):
                    consume(db,dict(claims,digest="d"*64),151)
                with self.assertRaises(ValueError):
                    consume(db,dict(claims,nonce="e"*32,digest="f"*64),200)
            db.close()
