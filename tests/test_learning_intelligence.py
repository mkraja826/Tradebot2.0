import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from recover_trading.learning_intelligence import clean, freeze, evaluate, feedback, read_rows

def dt(t):
    return datetime.fromtimestamp(t,timezone.utc).isoformat()

def row(i,opened,closed,enrolled,rule=True,win=True,symbol="XAUTUSD"):
    ident=f"{i:064x}";n="1" if win else "-1"
    d={"symbol":symbol,"decision_id":ident,"opened":dt(opened),"closed":dt(closed),
        "direction":"LONG","active_rules":["G01"] if rule else ["G02"],"net_before_funding":n,
        "gross_pnl":n,"fees":"0","learning_status":"observation_only","execution_effect":"none"}
    return ident,d["closed"],enrolled,json.dumps(d)

class LearningIntelligenceTests(unittest.TestCase):
    def test_no_future_or_cross_symbol_data(self):
        rows=[row(1,10,20,30),row(2,11,22,100),row(3,10,20,30,symbol="BTCUSD")]
        self.assertEqual(len(clean("XAUTUSD",rows,100)[0]),1)
        self.assertEqual(len(feedback("XAUTUSD",rows,100)["observations"]),1)
    def test_holdout_requires_new_open(self):
        rows=[row(1,10,20,30),row(2,90,110,120),row(3,110,130,140)]
        plan=freeze("XAUTUSD",rows,100,"G01","LONG","higher")
        result=evaluate(plan,rows,200)
        self.assertEqual(result["holdout_eligible_episodes"],1)
        self.assertEqual(result["status"],"insufficient_samples")
        self.assertEqual(result["validated_lessons"],[])
    def test_modified_plan_and_changed_baseline(self):
        rows=[row(1,10,20,30)]
        p=freeze("XAUTUSD",rows,100,"G01","LONG","higher")
        with self.assertRaises(ValueError):evaluate({**p,"rule":"G02"},rows,200)
        with self.assertRaises(ValueError):evaluate(p,[],200)
    def test_replication_is_not_validated_policy(self):
        rows=[]
        for i in range(40):
            rows.append(row(i+1,10+i*2,11+i*2,12+i*2,rule=i<20,win=i<20))
            rows.append(row(i+101,110+i*2,111+i*2,112+i*2,rule=i<20,win=i<20))
        p=freeze("XAUTUSD",rows,100,"G01","LONG","higher")
        r=evaluate(p,rows,300)
        self.assertEqual(r["status"],"descriptive_replication")
        self.assertFalse(r["causal_validation"])
        self.assertEqual(r["validated_lessons"],[])
    def test_missing_journal_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"learning.sqlite"
            self.assertIsNone(read_rows(p,"BTCUSD"))
            self.assertFalse(p.exists())
            self.assertEqual(feedback("BTCUSD",None,100)["status"],"journal_unavailable")
