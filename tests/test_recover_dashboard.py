import tempfile
import unittest
import sqlite3
import json
from pathlib import Path
from recover_trading.dashboard import report, query, STATIC

class DashboardTests(unittest.TestCase):
    def test_empty_does_not_create_db(self):
        with tempfile.TemporaryDirectory() as d:
            r=report(d,"BTCUSD")
            self.assertIsNone(r["orders"])
            self.assertIsNone(r["win_rate"])
            self.assertFalse((Path(d)/"BTCUSD").exists())
    def test_market_separation_and_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"BTCUSD";root.mkdir()
            with sqlite3.connect(root/"orders.sqlite") as db:
                db.execute("CREATE TABLE lifecycle_snapshots(id INTEGER PRIMARY KEY,symbol TEXT,observed INTEGER,detail TEXT)")
                db.execute("INSERT INTO lifecycle_snapshots VALUES(1,'BTCUSD',1,?)",(json.dumps({"wallets":[{"asset_symbol":"USD","balance":"500"}],"positions":[]}),))
            r=report(d,"BTCUSD")
            self.assertEqual(r["snapshot"]["wallets"][0]["balance"],"500")
            self.assertTrue(r["availability"]["positions"])
            self.assertIsNone(report(d,"XAUTUSD")["snapshot"])
    def test_reject_unknown_market(self):
        with self.assertRaises(ValueError):
            report(".", "../")
    def test_assets_present(self):
        for name in ("index.html","app.js","style.css"):
            self.assertTrue((STATIC/name).is_file())

    def test_forward_report_market_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"BTCUSD";root.mkdir()
            p=root/"forward_validation.json"
            p.write_text(json.dumps({"symbol":"XAUTUSD","version":"forward-reference-v1"}))
            self.assertIsNone(report(d,"BTCUSD")["forward_validation"])
            p.write_text(json.dumps({"symbol":"BTCUSD","version":"forward-reference-v1","outcomes":[]}))
            self.assertEqual(report(d,"BTCUSD")["forward_validation"]["outcomes"],[])
            p.write_text("{")
            self.assertIsNone(report(d,"BTCUSD")["forward_validation"])
