"""Offline regressions for failed/incomplete AI previews and closed sessions."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tradebot.ai import AIPlanner, PlanError, TradePlan, OrderIntent, _compact_market_context
from tradebot import cli


class PreviewRecoveryTests(unittest.TestCase):
    def _run(self, session, *, planner=None):
        snapshot = {
            "environment": "delta-india-demo",
            "collected_at": "2026-11-18T17:00:00+00:00",
            "session_phase": session,
        }
        with tempfile.TemporaryDirectory() as folder:
            output_path = Path(folder) / "preview.json"
            argv = ["tradebot", "preview", "--max-options", "8",
                    "--output", str(output_path)]
            with patch("sys.argv", argv), \
                 patch("tradebot.cli.DeltaDemo"), \
                 patch("tradebot.cli.collect_market_snapshot", return_value=snapshot), \
                 patch("tradebot.cli.record") as record, \
                 patch("tradebot.cli.recent", return_value=[]), \
                 patch("tradebot.cli.build_ai_context", return_value=(
                     {"coverage": {"quoted_futures": 1}},
                     [{"id": 1, "symbol": "BTCUSD"}])), \
                 patch("tradebot.cli.AIPlanner", return_value=planner) as planner_factory:
                buf = io.StringIO()
                try:
                    with redirect_stdout(buf):
                        cli.main()
                except SystemExit as exit_status:
                    status = exit_status.code
                else:
                    status = 0
                result = json.loads(buf.getvalue())
                self.assertEqual(result, json.loads(output_path.read_text()))
                self.assertFalse(result["orders_submitted"])
                return status, result, planner_factory.call_count, record.call_args

    def test_closed_session_skips_ai_and_spending(self):
        status, result, ai_init_count, journal = self._run("closed")
        self.assertEqual(status, 0)
        self.assertEqual(ai_init_count, 0)
        self.assertEqual(result["strategy"], "WAIT")
        self.assertEqual(result["orders"], [])
        self.assertFalse(result["ai_called"])
        self.assertEqual(result["decision_source"], "deterministic_session_gate_not_ai")
        self.assertEqual(journal.args[1], "session_gate_preview")

    def test_flatten_phase_skips_ai_and_spending(self):
        status, result, count, _ = self._run("flatten")
        self.assertEqual(status, 0)
        self.assertEqual(count, 0)
        self.assertEqual(result["orders"], [])
        self.assertFalse(result["ai_called"])

    def test_invalid_plan_is_not_mislabeled_as_model_wait(self):
        class BrokenPlanner:
            model = "tb-deepseek-v4-1-flash"
            last_finish_reason = "length"
            last_usage = {"prompt_tokens": 4000, "completion_tokens": 2048}
            call_count = 0

            def propose(self, *args):
                self.call_count += 1
                raise PlanError("AI response hit its completion-token limit; no plan accepted")

        planner = BrokenPlanner()
        status, result, count, journal = self._run("trading", planner=planner)
        self.assertEqual(status, 2)
        self.assertEqual(count, 1)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(result["orders"], [])
        self.assertNotIn("strategy", result)
        self.assertEqual(result["status"], "invalid_ai_response_no_plan")
        self.assertEqual(result["finish_reason"], "length")
        self.assertEqual(result["ai_tokens"]["completion_tokens"], 2048)
        self.assertEqual(journal.args[1], "ai_preview_rejected")

    def test_valid_plan_is_research_only(self):
        class WorkingPlanner:
            model = "tb-deepseek-v4-1-flash"
            last_usage = {"total_tokens": 450}
            def propose(self, *args):
                return TradePlan("Research hedge", "For testing only",
                                 (OrderIntent(1, "buy", 1),))

        status, result, count, journal = self._run(
            "trading", planner=WorkingPlanner())
        self.assertEqual(status, 0)
        self.assertEqual(result["decision_source"], "validated_ai_plan")
        self.assertEqual(result["orders"], [{"product_id": 1, "side": "buy", "size": 1}])
        self.assertFalse(result["orders_submitted"])
        self.assertEqual(journal.args[1], "ai_preview")

    def test_compacted_context_removes_duplicate_metadata_not_trade_evidence(self):
        sample = {
            "environment": "delta-india-demo",
            "session_phase": "trading",
            "collected_at": "2026-11-18T17:00:00+00:00",
            "core": {
                "best_bid": "90000", "best_ask": "90001",
                "book_age_seconds": 2,
                "ticker": {"spot_price": "90001", "age_seconds": 3,
                           "quotes": {"large_duplicate": "ignore"}},
            },
            "technical": {"return_1h_pct": 0.7, "realized_vol_1h_pct": 1.9,
                          "last_24": [{"time": i} for i in range(24)]},
            "futures": [],
            "options": [{"product_id": 72, "bid": "40", "ask": "41",
                         "ask_iv": "0.3", "greeks": {"delta": 0.2},
                         "volume": "123", "huge_duplicated_payload": "x" * 1000}],
            "demo_funds": {"wallets": []},
        }
        compact = _compact_market_context(sample)
        self.assertEqual(compact["options"][0]["ask"], "41")
        self.assertEqual(compact["options"][0]["greeks"]["delta"], 0.2)
        self.assertNotIn("huge_duplicated_payload", compact["options"][0])
        self.assertNotIn("quotes", compact["btc"])
        self.assertEqual(len(compact["technical"]["recent_candles"]), 8)


if __name__ == "__main__":
    unittest.main()
