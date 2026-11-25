import json,sqlite3,tempfile,unittest
from pathlib import Path
from recover_trading.management_report import report
class ManagementReportTests(unittest.TestCase):
    def test_counts_and_latency(self):
        with tempfile.TemporaryDirectory() as p:
            root=Path(p)
            with sqlite3.connect(root/"orders.sqlite") as db:
                db.execute("CREATE TABLE management_shadow(symbol,created,status,result)")
                db.execute("CREATE TABLE management_attempts(symbol,action,status)")
                for st,d in (("proposed",{"proposal":{"action":"maintain"},"diagnostics":{"elapsed_ms":1000}}),("failed",{"response_error":"http_520","diagnostics":{"elapsed_ms":3000}}),("prepared",{})):
                    db.execute("INSERT INTO management_shadow VALUES('BTCUSD',1,?,?)",(st,json.dumps(d)))
                db.execute("INSERT INTO management_attempts VALUES('BTCUSD','reduce','verified')")
            r=report(root,"BTCUSD",{"management_execution":{"enabled":True,"status":"awaiting_next_sample"}})
            self.assertEqual(r["median_response_ms"],2000)
            self.assertEqual(r["actions"],{"maintain":1})
            self.assertEqual(r["errors"],{"http_520":1})
            self.assertEqual(r["autonomous_attempts"][0]["count"],1)
            self.assertTrue(r["enabled"])
    def test_missing_journal(self):
        with tempfile.TemporaryDirectory() as p:
            r=report(p,"BTCUSD",{})
            self.assertEqual(r["status"],"incomplete_journal")
            self.assertEqual(r["manual_exchange_evidence"],[])
