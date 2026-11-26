import json,sqlite3,tempfile,unittest
from pathlib import Path
from recover_trading.research_context import prior, attach_context, replay, VERSION
class ResearchContextTests(unittest.TestCase):
    def test_prior_known_before_cutoff(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"learning.sqlite"
            db=sqlite3.connect(p)
            db.execute("CREATE TABLE lessons(symbol,decision_id,closed,enrolled,payload)")
            for i,enrolled in enumerate((30,100)):
                d={"symbol":"BTCUSD","decision_id":str(i),"opened":"1970-01-01T00:00:10Z","closed":"1970-01-01T00:00:20Z","direction":"LONG","learning_status":"observation_only","execution_effect":"none","gross_pnl":"1","fees":"2","net_before_funding":"-1"}
                db.execute("INSERT INTO lessons VALUES(?,?,?,?,?)",("BTCUSD",str(i),d["closed"],enrolled,json.dumps(d)))
            db.commit();db.close()
            r=prior(p,"BTCUSD",100)
            self.assertEqual(r["samples"],1)
            self.assertEqual(r["gross_positive_net_loss"],1)
            self.assertEqual(r["validated_lessons"],[])
    def test_default_and_cross_symbol_unchanged(self):
        c={"symbol":"BTCUSD","as_of":100}
        self.assertIs(attach_context(c,None),c)
        self.assertIs(attach_context(c,{"version":VERSION,"symbol":"XAUTUSD","as_of":100}),c)
    def test_current_entry_exposure(self):
        c={"symbol":"BTCUSD","as_of":100,"direction_engine":{"direction":"LONG"},
           "demo_account":{"leverage":20,"decision_quote":{"status":"fresh_book","best_bid":99,"best_ask":100},
           "product":{"symbol":"BTCUSD","contract_value":"0.1","notional_type":"vanilla","settling_asset":{"symbol":"USD"},"quoting_asset":{"symbol":"USD"}}}}
        r=attach_context(c,{"version":VERSION,"symbol":"BTCUSD","as_of":100})["research_evidence"]["current"]
        self.assertEqual(float(r["linear_exposure_per_contract"]["estimated_initial_margin_excluding_fees"]),.5)
        self.assertNotIn("research_evidence",c)
    def test_management_geometry(self):
        c={"symbol":"XAUTUSD","as_of":100,"position":{},"exit_geometry":{"current_gross_mark_return_bps":12}}
        r=attach_context(c,{"version":VERSION,"symbol":"XAUTUSD","as_of":100})["research_evidence"]["current"]
        self.assertEqual(r["position_geometry"]["current_gross_mark_return_bps"],"12")
    def test_missing_read_only(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"missing"
            self.assertEqual(prior(p,"BTCUSD",100)["status"],"unavailable")
            self.assertEqual(replay(p,"BTCUSD",p)["status"],"no_data")
            self.assertFalse(p.exists())
