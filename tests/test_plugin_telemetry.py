import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from recover_trading.plugin_telemetry import report

class PluginTelemetryTests(unittest.TestCase):
    def test_missing_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=report("BTCUSD",tmp,now=100)
            self.assertEqual(r["journal_status"],"incomplete")
            self.assertFalse(r["heartbeat"]["fresh"])
            self.assertFalse((Path(tmp)/"BTCUSD").exists())
            with self.assertRaises(ValueError):
                report("../",tmp)
    def test_proposal_and_verified_attempt_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"BTCUSD";p.mkdir()
            (p/"status.json").write_text(json.dumps({"timestamp":90,"entry_model":"tb-gpt-6",
                "management_model":"tb-deepseek-v4-pro","management_execution":{"enabled":True}}))
            with sqlite3.connect(p/"orders.sqlite") as db:
                db.execute("CREATE TABLE management_shadow(id,created,model,status,result,symbol)")
                db.execute("CREATE TABLE management_attempts(proposal_id,created,action,status,detail,symbol)")
                d=json.dumps({"proposal":{"action":"reduce","contracts":3,"reason":"not exported"},
                    "diagnostics":{"elapsed_ms":6000,"usage":{"total_tokens":1500}}})
                for ident,s in (("btc","BTCUSD"),("gold","XAUTUSD")):
                    db.execute("INSERT INTO management_shadow VALUES(?,?,?,?,?,?)",
                        (ident,95,"tb-deepseek-v4-pro","proposed",d,s))
                db.execute("INSERT INTO management_attempts VALUES(?,?,?,?,?,?)",
                    ("btc",96,"reduce","verified",json.dumps({"observed_size":7,"plan":{"before_size":10,
                     "expected_size":7},"evidence":{"status":"partial_close_observed"},"secret":"hidden"}),"BTCUSD"))
            r=report("BTCUSD",tmp,now=100)
            self.assertTrue(r["heartbeat"]["fresh"])
            self.assertEqual(len(r["recent_proposals"]),1)
            self.assertEqual(r["recent_proposals"][0]["usage"]["total_tokens"],1500)
            self.assertTrue(r["recent_attempts"][0]["exchange_verified"])
            self.assertNotIn("hidden",json.dumps(r))
            self.assertNotIn("not exported",json.dumps(r))
            self.assertFalse(report("BTCUSD",tmp,now=300)["heartbeat"]["fresh"])
