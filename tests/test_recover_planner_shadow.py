import unittest,tempfile,sqlite3
from pathlib import Path
from contextlib import closing
from recover_trading.planner_shadow import packet,research_summary,ShadowJournal
from recover_trading.direction import direction_for
from test_recover_decision import report
class PlannerShadowTests(unittest.TestCase):
    def test_reference_availability_and_dedup(self):
        r=report("BTCUSD"); d=direction_for(r); at=r["as_of"]
        ref={"version":"planner-reference-v1","symbol":"BTCUSD","built_at":at+1,"dataset_end":at-1,
            "development_end":at-2,"stride_s":7200,"assumed_cost_bps":15,"positive_training_candidates":0,
            "validation":"exploratory","rules":{}}
        a=packet(r,d,ref)
        self.assertEqual(a["reference_research"]["status"],"unavailable_at_decision")
        ref["built_at"]=at
        b=packet(r,d,ref)
        self.assertEqual(b["reference_research"]["status"],"available")
        self.assertEqual(b["execution_effect"],"none")
        self.assertNotIn("demo_account",b)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"shadow.sqlite"; j=ShadowJournal(p);j.record(b);j.record(b)
            with closing(sqlite3.connect(p)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM planner_packets").fetchone()[0],1)
    def test_summary_excludes_holdout(self):
        row={"partition":"development","regime":"all","rule_id":"B01","horizon_s":900,"samples":2,"mean_net_bps":-15,"mean_gross_bps":0,"win_rate":0}
        r={"complete":True,"symbol":"BTCUSD","start":1,"split":100,"end":200,"stride_s":7200,"cost_bps_round_trip":15,"results":[row,dict(row,partition="holdout",mean_net_bps=1000)]}
        c={"symbol":"BTCUSD","development_end_exclusive":100,"positive_training_candidates":0}
        s=research_summary(r,c,built_at=201)
        self.assertEqual(len(s["rules"]["B01"]),1)
        self.assertEqual(s["rules"]["B01"][0]["mean_net_bps"],-15)
        with self.assertRaises(ValueError):research_summary(r,c,built_at=199)
