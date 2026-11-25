import unittest
from datetime import datetime,timezone
from recover_trading.performance_analytics import build,scope
class AnalyticsTests(unittest.TestCase):
    def row(self,i,n,side="SHORT",owned=True):
        return {"opened":f"2026-11-24T00:{i:02}:00Z","closed":f"2026-11-24T01:{i:02}:00Z","direction":side,"net_before_funding":str(n),"decision_id":str(i) if owned else None,"attribution":"single_recover_entry_order" if owned else "unattributed"}
    def test_net_factor_drawdown_and_scope(self):
        rows=[self.row(1,10),self.row(2,-4),self.row(3,-8,"LONG"),self.row(4,5,owned=False)]
        now=int(datetime(2026,11,25,tzinfo=timezone.utc).timestamp())
        p={"status":"reconciled_subset","currency":"USD","recent_episodes":rows,"recover_attributed":{"closed_episodes":3},"all_reconciled":{"closed_episodes":4}}
        r=build(p,{},now)
        self.assertEqual(r["recover"]["net"],"-2");self.assertEqual(r["recover"]["max_closed_pnl_drawdown"],"12")
        self.assertAlmostEqual(float(r["recover"]["profit_factor"]),10/12)
        self.assertEqual(r["account"]["net"],"3");self.assertEqual(r["account"]["calendar"][-2]["net"],"3")
        self.assertIsNone(r["account"]["calendar"][-1]["net"])
    def test_no_losses_truncation_and_tied_closure(self):
        a=self.row(1,5);b=self.row(2,-3);b["closed"]=a["closed"]
        r=scope([a,b],4,[],1795619000)
        self.assertTrue(r["truncated"]);self.assertEqual(len(r["curve"]),1);self.assertEqual(r["max_closed_pnl_drawdown"],"0")
        r=scope([a],1,[],1795619000);self.assertIsNone(r["profit_factor"]);self.assertEqual(r["profit_factor_status"],"no_losing_episodes")
    def test_retention_exact_evidence(self):
        a=self.row(1,5)
        x={**a,"status":"complete_interior_lower_bound","coverage":1,"mfe_bps":100,"gross_weighted_exit_return_bps":60,"observed_capture_upper_bound_pct":60,"realized_net_before_funding":"5"}
        r=scope([a],1,[x],1795619000)
        self.assertEqual(r["retention"]["median_capture_upper_bound_pct"],60)
        self.assertEqual(scope([a],1,[x,x],1795619000)["retention"]["eligible_episodes"],0)
        self.assertEqual(scope([a],1,[{**x,"coverage":.5}],1795619000)["retention"]["eligible_episodes"],0)
    def test_unavailable_and_invalid_rows(self):
        self.assertEqual(build({}, {},0)["status"],"unavailable")
        a=self.row(1,5);self.assertEqual(scope([a,a],2,[],1795619000)["status"],"unavailable")
