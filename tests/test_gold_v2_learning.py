import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from recover_trading.gold_v2_learning import analyze,read_report,COHORT

def row(t,exit_value=30,scale_value=20,fixed=10,*,resolved=None,missing=False):
    evidence={"symbol":"XAUTUSD","version":"test-engine","regime":"trend",
              "intelligence":{"version":"test-score","candidates":[]}}
    packets={}
    for cost in ("15","30"):
        values={"fixed":fixed,"hybrid_exit":exit_value,"hybrid_scaling":scale_value}
        packets[cost]={"version":"test-combined","results":{
            p:{"status":"observed","net_bps_initial_notional":v} for p,v in values.items()}}
    if missing:packets["30"]["results"]["hybrid_exit"]={"status":"ambiguous_intrabar"}
    outcome={"status":"evaluated","candidates":[{"family":"trend_pullback","direction":"LONG","combined":packets}]}
    return {"signal_boundary":t,"end_boundary":t+10,"resolved_at":t+20 if resolved is None else resolved,
            "policy_version":COHORT,"status":"resolved","evidence":json.dumps(evidence),
            "outcome_json":json.dumps(outcome)}

def study(rows):
    return analyze(rows,cutoff=100,as_of=300,min_train=2,min_eval=2)
class LearningTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(study([])["proposals"],[])
    def test_positive_holdout(self):
        x=study([row(10),row(40),row(110),row(150)])["proposals"][0]
        self.assertEqual(x["selected_on_training"],"hybrid_exit")
        self.assertEqual(x["status"],"positive_holdout_observation")
    def test_holdout_not_used_to_select(self):
        x=study([row(10),row(40),row(110,exit_value=-20,scale_value=100),
                 row(150,exit_value=-20,scale_value=100)])["proposals"][0]
        self.assertEqual(x["selected_on_training"],"hybrid_exit")
        self.assertEqual(x["status"],"holdout_not_confirmed")
    def test_late_resolution_excluded(self):
        x=study([row(10),row(40,resolved=101),row(110),row(150)])
        self.assertEqual(x["exclusions"]["crosses_training_cutoff"],1)
        self.assertEqual(x["proposals"][0]["status"],"insufficient_training")
    def test_future_resolution_excluded(self):
        x=study([row(10),row(40),row(110,resolved=301)])
        self.assertEqual(x["exclusions"]["not_resolved_at_as_of"],1)
        self.assertEqual(x["proposals"][0]["evaluation_samples"],0)
    def test_missing_policy_excluded_from_all_pairs(self):
        x=study([row(10),row(40,missing=True),row(110),row(150)])["proposals"][0]
        self.assertEqual(x["excluded_train"],1)
        self.assertEqual(x["train_samples"],1)
    def test_no_training_improvement(self):
        x=study([row(10,0,0),row(40,0,0),row(110),row(150)])["proposals"][0]
        self.assertEqual(x["selected_on_training"],"fixed")
        self.assertEqual(x["status"],"no_training_improvement")
    def test_old_cohort_excluded(self):
        x=study([dict(row(10),policy_version="gold-v2-validation.4")])
        self.assertEqual(x["exclusions"]["different_policy_cohort"],1)
    def test_duplicate_window_rejected(self):
        with self.assertRaises(ValueError):study([row(10),row(10)])
    def test_read_only_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"missing.sqlite"
            with self.assertRaises(sqlite3.OperationalError):read_report(p,cutoff=100,as_of=300)
            self.assertFalse(p.exists())
