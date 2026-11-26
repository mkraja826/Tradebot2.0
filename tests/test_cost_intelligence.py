import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from recover_trading.cost_intelligence import usage_report, token_usage, trade_cost, summarize, report, price_schedule

class CostIntelligenceTests(unittest.TestCase):
    def test_failed_calls_and_missing_usage(self):
        raw=json.dumps({"diagnostics":{"usage":{"prompt_tokens":1000,"completion_tokens":200,"total_tokens":1200}}})
        rows=[("a","model","proposed",1,raw),("b","model","failed",2,raw),("c","model","failed",3,"{}")]
        rates=price_schedule({"model":{"currency":"USD","input_per_million":"1","output_per_million":"5"}})
        g=usage_report(rows,[],rates)["groups"][0]
        self.assertEqual(g["usage_rows"],2)
        self.assertEqual(g["missing_usage_rows"],1)
        self.assertEqual(Decimal(g["estimated_reported_token_cost"]),Decimal("0.004"))
        self.assertIsNone(g["actual_billed_cost"])
        self.assertFalse(g["usage_coverage_complete"])
    def test_inconsistent_tokens(self):
        self.assertIsNone(token_usage({"diagnostics":{"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":20}}}))
    def test_fee_loss_and_currency(self):
        e={"gross_pnl":"1","fees":"2","net_before_funding":"-1","reported_funding":None}
        a=trade_cost(e,{"currency":"USD","fill_notional":"1000"})
        self.assertTrue(a["fees_exceed_positive_gross"])
        self.assertEqual(Decimal(a["round_trip_fee_bps_of_entry_notional"]),20)
        self.assertIsNone(a["funding_adjusted_net"])
        b=trade_cost(e,{"currency":"INR"})
        self.assertEqual(len(summarize([a,b])),2)
    def test_no_rate_no_cost(self):
        raw=json.dumps({"diagnostics":{"usage":{"prompt_tokens":1,"completion_tokens":2}}})
        self.assertIsNone(usage_report([], [("a","model","proposed",1,raw)])["groups"][0]["estimated_reported_token_cost"])
    def test_missing_journals_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"BTCUSD"
            r=report(root,"BTCUSD",0,100)
            self.assertFalse(root.exists())
            self.assertIsNone(r["combined_after_all_costs"])
            self.assertFalse(r["ai_usage"]["entry_journal_available"])
