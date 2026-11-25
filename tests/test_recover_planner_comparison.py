import unittest,tempfile,sqlite3,json
from pathlib import Path
from contextlib import closing
from recover_trading.planner_comparison import make_pair,run
class PlannerComparisonTests(unittest.TestCase):
    def test_time_identity_and_baseline_unchanged(self):
        t=1800000000;c={"symbol":"BTCUSD","as_of":t,"market":{},"direction_engine":{"direction":"LONG"}}
        ref={"symbol":"BTCUSD","version":"reference-strategy-v1","as_of":t-300,"generated":t-20,"completed":t-10,"matched_reference":{"direction":"SHORT"}}
        p=make_pair("BTCUSD","d","fixture",t,c,ref,None)
        self.assertEqual(p["evidence_status"],"reference_only")
        self.assertEqual(p["baseline"]["direction_engine"],p["alternative"]["direction_engine"])
        self.assertNotIn("experimental_reference_evidence",p["baseline"])
        ref["completed"]=t
        self.assertEqual(make_pair("BTCUSD","d","fixture",t,c,ref,None)["evidence_status"],"unavailable")
        ref["completed"]=t-10;ref["symbol"]="XAUTUSD"
        self.assertEqual(make_pair("BTCUSD","d","fixture",t,c,ref,None)["evidence_status"],"unavailable")
    def test_protocol_never_enrolls_old_and_deduplicates(self):
        t=1800000000
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"BTCUSD";root.mkdir()
            with closing(sqlite3.connect(root/"decisions.sqlite")) as db,db:
                db.execute("CREATE TABLE decisions(id TEXT,symbol TEXT,model TEXT,created INTEGER,context TEXT)")
                db.execute("INSERT INTO decisions VALUES(?,?,?,?,?)",("old","BTCUSD","fixture",t-1,json.dumps({"symbol":"BTCUSD","as_of":t-2})))
            a=run(d,"BTCUSD",t)
            self.assertEqual(a["prepared_pairs"],0);self.assertIsNotNone(a["retrospective_input_preview"])
            with closing(sqlite3.connect(root/"decisions.sqlite")) as db,db:
                db.execute("INSERT INTO decisions VALUES(?,?,?,?,?)",("new","BTCUSD","fixture",t+1,json.dumps({"symbol":"BTCUSD","as_of":t+1})))
            self.assertEqual(run(d,"BTCUSD",t+2)["prepared_pairs"],1)
            self.assertEqual(run(d,"BTCUSD",t+3)["prepared_pairs"],1)
