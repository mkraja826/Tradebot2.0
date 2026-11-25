import tempfile
import unittest
from pathlib import Path
from recover_trading.direction import direction_for, compact_context, REGISTRY
from recover_trading.decision import DecisionJournal, evaluate_report
from test_recover_decision import report, Fake

def sig(ident,frame,side):
    return {"id":ident,"frame":frame,"direction":side,"closed_at":1800000000}

class DirectionTests(unittest.TestCase):
    def test_registry_preserves_all_100_candidates(self):
        self.assertEqual(sum(len(r)+len(d) for r,d in REGISTRY.values()),100)
        self.assertEqual(sum(len(r) for r,d in REGISTRY.values()),95)
    def test_one_rule_one_vote_and_conflicts(self):
        r=report()
        r["signals"]=[sig("B01","5m","LONG"),sig("B01","15m","LONG"),
                      sig("B02","1h","SHORT"),sig("B02","4h","LONG"),
                      sig("B03","5m","SHORT")]
        x=direction_for(r)
        self.assertEqual((x["long_votes"],x["short_votes"],x["conflicting_rules"],x["direction"]),(1,1,1,"NEUTRAL"))
        r["signals"].append(sig("B04","5m","LONG"))
        self.assertEqual(direction_for(r)["direction"],"LONG")
    def test_neutral_never_calls_provider_and_side_mismatch_never_proposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=DecisionJournal(Path(tmp)/"db"); p=Fake(); models={"BTCUSD":"test"}
            r=report(); r["signals"]=[sig("B01","5m","LONG"),sig("B03","5m","SHORT")]
            self.assertEqual(evaluate_report(r,j,p,models)["status"],"direction_neutral")
            self.assertEqual(p.calls,0)
            r["signals"]=[sig("B01","5m","LONG")]
            out=evaluate_report(r,j,p,models)
            self.assertEqual(out["response_error"],"direction_mismatch")
            self.assertEqual(out["status"],"failed")
    def test_compaction_keeps_direction_account_and_current_levels(self):
        c={"direction_engine":{"direction":"SHORT"},"demo_account":{"wallets":[]},
           "market":{"frames":{"5m":{"status":"ready","features":{"atr14":2,"unused":3},
                                   "previous_features":{"large":list(range(500))}}},"quotes":{"book":{"bid":100,"levels":[1,2]}}}}
        out=compact_context(c)
        self.assertEqual(out["direction_engine"],c["direction_engine"])
        self.assertEqual(out["demo_account"],c["demo_account"])
        self.assertEqual(out["market"]["frames"]["5m"]["features"],{"atr14":2})
        self.assertNotIn("previous_features",out["market"]["frames"]["5m"])
        self.assertEqual(out["market"]["quotes"]["book"],{"bid":100})
