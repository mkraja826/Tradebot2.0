import json
import tempfile
import unittest
from pathlib import Path
from recover_trading.trade_intelligence import build, exposure, report

class TradeIntelligenceTests(unittest.TestCase):
    def test_missing_journals_do_not_create_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"BTCUSD"
            r=report(p,"BTCUSD",Path(tmp)/"learning")
            self.assertFalse(r["coverage"]["decision_journal_available"])
            self.assertFalse(p.exists())
            self.assertEqual(r["execution_effect"],"none")
    def test_exposure_estimate(self):
        c={"demo_account":{"product":{"notional_type":"vanilla","contract_value":"0.001",
            "settling_asset":{"symbol":"USD"},"quoting_asset":{"symbol":"USD"}}}}
        r={"side":"buy","leverage":20,"stop_loss":59000,"take_profit":62000,"size":10}
        e=exposure(c,r,{"filled_contracts":"10","average_fill_price":"60000"})
        self.assertEqual(float(e["fill_notional"]),600)
        self.assertEqual(float(e["estimated_initial_margin_excluding_fees"]),30)
        self.assertEqual(float(e["planned_stop_loss_amount_at_fill"]),10)
        self.assertEqual(float(e["planned_target_gain_at_fill"]),20)
        self.assertIsNone(exposure({},r,{})["fill_notional"])
    def test_join_and_flags(self):
        e={"decision_id":"a","opened":"2026-11-25T00:00:00Z","closed":"2026-11-25T00:10:00Z",
           "direction":"LONG","attribution":"single_recover_entry_order","gross_pnl":"1","fees":"2","net_before_funding":"-1"}
        p={"status":"reconciled_subset","recover_attributed":{"closed_episodes":2},"recent_episodes":[e]}
        rv={"id":"a","outcome":"closed_reconciled","net_before_funding":"-1","fill_target_bps":-5}
        x={**e,"status":"complete_interior_lower_bound","mfe_bps":1064}
        l={**e,"learning_status":"observation_only"}
        d=("a","actual-model","proposed","{}",json.dumps({"symbol":"BTCUSD","action":"trade","reason":"observed"}))
        out=build("BTCUSD",p,{"recent":[rv]},{"episodes":[x]},{"lessons":[l]},[d],[])
        row=out["trades"][0]
        self.assertEqual(row["entry"]["model"],"actual-model")
        self.assertFalse(out["coverage"]["complete_window"])
        self.assertIn("large_excursion_requires_data_review",row["data_quality_notes"])
        self.assertIn("target_beyond_fill_in_wrong_direction",row["data_quality_notes"])
        self.assertIn("fees_exceeded_gross_gain",row["data_quality_notes"])
        self.assertEqual(row["learning_status"],"observation_only")
    def test_management_time_match_is_not_causal_attribution(self):
        from recover_trading.trade_intelligence import management_candidates
        e={"opened":"1970-01-01T00:01:00Z","closed":"1970-01-01T00:03:00Z","direction":"LONG"}
        c=json.dumps({"position":{"direction":"long"},"execution_identity":{"created_at":"x"}})
        r=json.dumps({"proposal":{"action":"reduce"}})
        a=json.dumps({"identity":{"created_at":"x"}})
        rows=[("a",100,"actual-manager","proposed",c,r,110,"reduce","verified",a),
              ("b",180,"other","proposed",c,r,180,"reduce","verified",a),
              ("c",120,"actual-manager","proposed",c,r,130,"reduce","verified","{}")]
        result=management_candidates(e,rows)
        self.assertEqual(len(result),2)
        self.assertTrue(result[0]["attempt"]["journal_verified"])
        self.assertFalse(result[1]["attempt"]["journal_verified"])
        self.assertIn("not_proven",result[0]["association"])
