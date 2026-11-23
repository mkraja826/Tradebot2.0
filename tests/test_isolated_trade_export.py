"""Regression tests for isolated demo CSV review export."""
from contextlib import redirect_stderr, closing
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import os
import sqlite3
import stat
import unittest
from tradebot.isolated_trade_export import collect, main, read_account

class IsolatedExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.root.mkdir()
        for label, filename in (("btc-isolated","fire-ops.sqlite"),
                                ("gold-isolated","fire-xaut.sqlite")):
            child = self.root / label
            child.mkdir()
            with closing(sqlite3.connect(child / filename)) as db:
                db.execute("CREATE TABLE fire_requests("
                           "press TEXT,created_at TEXT,updated_at TEXT,"
                           "status TEXT,result TEXT)")
                is_btc = label == "btc-isolated"
                receipt = ({"model":"gpt6","orders_submitted":True,
                            "entry":{"price":"61200"},"direction":"LONG",
                            "risk_assessment":{"expected_net_reward_risk":"0.5"},
                            "risk_quote_diagnostics":{"source":"unit_test",
                                "broker":{"gross_1_to_1_satisfied":False}}}
                           if is_btc else
                           {"model":"deepseek","orders_submitted":False,
                            "reason_code":"risk_governor_failed"})
                db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                           (("a" if is_btc else "b")*32,
                            "2026-11-23T12:00:00+00:00",
                            "2026-11-23T12:01:00+00:00",
                            "flat_verified" if is_btc else "rejected_no_order",
                            json.dumps(receipt)))
                db.commit()

    def test_accounts_independent_and_rejections_included(self):
        rows = collect(self.root)
        self.assertEqual([r["symbol"] for r in rows], ["BTCUSD", "XAUTUSD"])
        self.assertEqual(len(collect(self.root,"BTCUSD")),1)
        self.assertEqual(rows[0]["entry_fill_price"],"61200")
        self.assertEqual(json.loads(rows[0]["risk_quote_diagnostics_json"])[
            "source"], "unit_test")
        self.assertEqual(json.loads(rows[1]["risk_quote_diagnostics_json"]), {})
        self.assertEqual(rows[1]["reason_code"],"risk_governor_failed")

    def test_never_auto_classifies_or_invents_pnl(self):
        for row in collect(self.root):
            for key in ("broker_verified_net_pnl_usd","manual_review_label",
                        "manual_notes"):
                self.assertEqual(row[key],"")

    def test_missing_or_symlinked_ledger_fails(self):
        p=self.root/"gold-isolated"/"fire-xaut.sqlite"
        p.unlink()
        self.assertRaises(ValueError,read_account,self.root,"XAUTUSD")
        os.symlink(self.root/"btc-isolated"/"fire-ops.sqlite",p)
        self.assertRaises(ValueError,read_account,self.root,"XAUTUSD")

    def test_invalid_receipt_fails_closed(self):
        p=self.root/"btc-isolated"/"fire-ops.sqlite"
        with closing(sqlite3.connect(p)) as db:
            db.execute("UPDATE fire_requests SET result='not-json'")
            db.commit()
        self.assertRaises(ValueError,collect,self.root)

    def test_private_csv_does_not_overwrite(self):
        path=Path(self.temp.name)/"export.csv"
        with redirect_stderr(StringIO()):
            self.assertEqual(main(["--data-dir",str(self.root),
                                   "--output",str(path)]),0)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        with path.open(newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]["manual_review_label"],"")
        self.assertRaises(FileExistsError,main,
                          ["--data-dir",str(self.root),"--output",str(path)])

if __name__ == "__main__":
    unittest.main()