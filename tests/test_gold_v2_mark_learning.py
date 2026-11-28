import unittest,json
from tempfile import TemporaryDirectory
from pathlib import Path
from recover_trading.gold_v2_mark_learning import analyze,read_report
from recover_trading.gold_v2_hybrid_validation import HybridJournal
from recover_trading.gold_v2_hybrid import MARK_SOURCE
from recover_trading.gold_v2_quote_management import VERSION,POLICIES

START=3600000
CUT=START+3*7200
END=CUT+3*7200
def row(i,exit_value=30,scale_value=20,macro="aligned",model="gold-v2-mark-model.2"):
    b=START+i*7200
    evidence={"signal_source":MARK_SOURCE,"execution_eligible":False,"model_version":model,
        "management_version":VERSION,"macro_annotation":{"candidate_groups":[{"family":"fixture","direction":"LONG","macro_group":macro}]}}
    management={"version":VERSION,"results":{c:{p:{"net_bps_initial_notional":v-(0 if c=="15" else 5),"fill_verified":False}
        for p,v in zip(POLICIES,(10,exit_value,scale_value))} for c in ("15","30")}}
    result={"status":"sampled_outcomes","fill_verified":False,"results":[{"family":"fixture","direction":"LONG","management":management}]}
    return {"boundary":b,"enrolled":b+10,"resolved":b+3610,"evidence":json.dumps(evidence),"outcome":json.dumps(result)}
def report(rows):
    return analyze(rows,cutoff=CUT,as_of=END,min_train=2,min_holdout=2)
class MarkLearningTests(unittest.TestCase):
    def test_training_selection_frozen(self):
        x=report([row(0),row(1),row(3,0,100),row(4,0,100)])
        p=next(p for p in x["proposals"] if p["macro_group"]=="all")
        self.assertEqual(p["selected_on_training"],"adaptive_exit")
        self.assertEqual(p["status"],"holdout_not_confirmed")
        self.assertFalse(x["automatic_promotion"])
    def test_positive_holdout(self):
        x=report([row(i) for i in (0,1,3,4)])
        self.assertTrue(all(p["status"]=="positive_holdout_observation" for p in x["proposals"]))
        self.assertEqual(len(x["training_entry_ranking"]),1)
    def test_unknown_macro_separate(self):
        x=report([row(0,macro="unknown"),row(1),row(3),row(4)])
        self.assertEqual({p["macro_group"] for p in x["proposals"]},{"all","aligned","unknown"})
    def test_cutoff_leakage_excluded(self):
        r=row(2);r["resolved"]=CUT+1
        x=report([row(0),row(1),r,row(3)])
        self.assertEqual(x["exclusions"]["crosses_cutoff"],1)
    def test_overlapping_windows_refused(self):
        a,b=row(0),row(1);b.update(boundary=START+300,enrolled=START+310,resolved=START+3910)
        with self.assertRaisesRegex(ValueError,"overlapping_sample_windows"):report([a,b])
    def test_model_versions_separate(self):
        x=report([row(0),row(1,model="gold-v2-mark-model.1"),row(3),row(4)])
        self.assertTrue(all(p["status"]=="insufficient_training" for p in x["proposals"]))
    def test_read_only_empty_and_wrong_source(self):
        with TemporaryDirectory() as t:
            p=Path(t)/"mark.sqlite";j=HybridJournal(p,source=MARK_SOURCE);j.close()
            self.assertEqual(read_report(p,cutoff=CUT,as_of=END)["proposals"],[])
            p=Path(t)/"trade.sqlite";j=HybridJournal(p);j.close()
            with self.assertRaisesRegex(ValueError,"wrong_study"):read_report(p,cutoff=CUT,as_of=END)
