"""Offline crypto 24/7 demo scheduling and fail-closed execution tests."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from tradebot.ai import OrderIntent, TradePlan
from tradebot.delta import DEMO_API
from tradebot.execution import DemoExecutor, ExecutionError
from tradebot.preflight import check_entry
from tradebot.runner import BotRunner, RunnerConfig
from tradebot.session import SessionPhase, entry_phase, session_phase
from test_runner import FakeExchange, make_snapshot, FUTURE, CALL

WEEKEND = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)


class ContinuousCryptoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "bot.jsonl")
        self.now = WEEKEND
        self.exchange = FakeExchange()
        self.planner = Mock()
        self.planner.propose.return_value = TradePlan(
            "24x7 BTC futures research", "Fresh BTC market evidence", (
                OrderIntent(1, "buy", 1),))
        def fresh_ticker(symbol):
            return {
                "symbol": symbol,
                "timestamp": int(self.now.timestamp()) - 1,
                "quotes": {"best_bid": "90000", "best_ask": "90001"},
            }
        self.exchange.ticker = fresh_ticker

    def runner(self, *, mode="observe", **overrides):
        config = RunnerConfig(
            mode=mode, schedule="crypto-24x7", journal_path=self.path,
            ai_interval_seconds=300, max_hold_seconds=900, **overrides
        )
        return BotRunner(self.exchange, self.planner, config=config,
                         now=lambda: self.now,
                         snapshot_fn=lambda *a, **kw: make_snapshot(self.now))

    def test_default_remains_nyse_closed_weekends(self):
        self.assertEqual(session_phase(WEEKEND), SessionPhase.CLOSED)
        self.assertEqual(entry_phase(WEEKEND), SessionPhase.CLOSED)
        self.assertEqual(entry_phase(WEEKEND, schedule="crypto-24x7"),
                         SessionPhase.TRADING)

    def test_observe_scans_weekends_without_orders(self):
        runner = self.runner()
        result = runner.tick()
        self.assertEqual(result["action"], "preview")
        self.planner.propose.assert_called_once()
        self.assertEqual(self.exchange.trades, [])
        context = self.planner.propose.call_args.args[0]
        self.assertEqual(context["trading_schedule"], "crypto-24x7")
        self.assertEqual(context["session_phase"], "trading")

    def test_preflight_accepts_valid_weekend_fresh_quotes(self):
        result = check_entry(
            self.exchange, self.planner.propose.return_value,
            [FUTURE, CALL], now=self.now, schedule="crypto-24x7")
        self.assertEqual(result.quoted_legs, 1)

    def test_nyse_executor_still_rejects_weekends(self):
        self.exchange.allow_orders = True
        engine = DemoExecutor(self.exchange, now=lambda: self.now,
                              journal_path=self.path, pause=lambda x: None)
        with self.assertRaises(ExecutionError):
            engine.execute(self.planner.propose.return_value, [FUTURE, CALL])
        self.assertEqual(self.exchange.trades, [])

    def test_pilot_limits_contracts_and_legs_before_order(self):
        self.exchange.allow_orders = True
        self.planner.propose.return_value = TradePlan(
            "oversized", "Rejected pilot proposal",
            (OrderIntent(1, "buy", 2),))
        result = self.runner(mode="demo").tick()
        self.assertEqual(result["action"], "risk_rejected")
        self.assertFalse(result["orders_submitted"])
        self.assertEqual(self.exchange.trades, [])

    def test_weekend_demo_entry_cannot_stack_and_times_out(self):
        self.exchange.allow_orders = True
        runner = self.runner(mode="demo")
        result = runner.tick()
        self.assertEqual(result["action"], "demo_order_submitted")
        self.assertEqual(self.exchange.positions, {1: 1})
        self.now += timedelta(minutes=1)
        self.assertEqual(runner.tick()["action"], "holding_existing_position")
        self.assertEqual(len(self.exchange.trades), 1)
        self.now += timedelta(minutes=16)
        self.assertEqual(runner.tick()["action"], "time_stop_flat")
        self.assertEqual(self.exchange.positions[1], 0)
        self.assertTrue(self.exchange.trades[-1][3])

    def test_orphan_position_triggers_closeout_and_persistent_halt(self):
        self.exchange.allow_orders = True
        self.exchange.positions[1] = 2
        runner = self.runner(mode="demo")
        self.assertEqual(runner.tick()["action"], "halted_orphan_position")
        self.assertEqual(self.exchange.positions[1], 0)
        self.assertTrue(Path(self.path + ".crypto24x7-halt").exists())
        # The stop survives a service restart.
        new_runner = self.runner(mode="demo")
        self.assertEqual(new_runner.tick()["action"], "halted_persistent")
        self.planner.propose.assert_not_called()

    def test_disabled_demo_mode_does_not_trade(self):
        runner = self.runner()
        self.assertEqual(runner.tick()["action"], "preview")
        self.assertFalse(self.exchange.allow_orders)
        self.assertEqual(self.exchange.trades, [])

    def test_bad_schedule_and_risk_limits_rejected(self):
        with self.assertRaises(ValueError):
            RunnerConfig(schedule="invalid")
        with self.assertRaises(ValueError):
            RunnerConfig(schedule="crypto-24x7", max_hold_seconds=0)
        with self.assertRaises(ValueError):
            RunnerConfig(schedule="crypto-24x7", max_contracts_per_leg=100)


if __name__ == "__main__":
    unittest.main()
