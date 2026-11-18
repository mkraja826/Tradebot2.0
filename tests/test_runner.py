import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from tradebot.ai import OrderIntent, TradePlan
from tradebot.delta import DEMO_API
from tradebot.runner import (
    BotRunner, ExposureAlert, RunnerConfig, RunnerError, SingleInstance
)

OPEN = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
CLOSEOUT = datetime(2026, 11, 18, 20, 50, tzinfo=timezone.utc)
WEEKEND = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)
FUTURE = {"id": 1, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
          "state": "live"}
CALL = {"id": 2, "symbol": "C-BTC-90000-271126",
        "contract_type": "call_options", "state": "live"}


def make_snapshot(at=OPEN):
    def quote(product):
        return {
            "product_id": product["id"], "symbol": product["symbol"],
            "contract_type": product["contract_type"],
            "usable_quote": True,
            "bid": "90000", "ask": "90001",
            "strike_price": "90000", "settlement_time": "2026-11-27",
        }
    return {
        "environment": "delta-india-demo",
        "session_phase": "trading",
        "collected_at": at.isoformat(),
        "core": {"best_bid": "90000", "best_ask": "90001",
                 "ticker": {"spot_price": "90000"}},
        "technical": {"return_1h_pct": 0.1, "realized_vol_1h_pct": 1.1},
        "futures": [quote(FUTURE)],
        "options": [quote(CALL)],
        "demo_funds": {
            "net_equity": "10000",
            "wallets": [{"asset": "USD", "available_balance": "9000"}],
        },
    }


class FakeExchange:
    base_url = DEMO_API

    def __init__(self, *, allow_orders=False):
        self.allow_orders = allow_orders
        self.pending = []
        self.positions = {}
        self.trades = []
        self.stale = False
        self.insufficient_margin = False
        self.ticker_reads = 0

    def open_orders(self):
        return list(self.pending)

    def btc_positions(self):
        return [{"product_id": pid, "size": size}
                for pid, size in self.positions.items() if size != 0]

    def wallet_balances(self):
        return {"balances": [{"asset_symbol": "USD",
                              "available_balance": "9000"}],
                "meta": {"net_equity": "10000"}}

    def ticker(self, symbol):
        self.ticker_reads += 1
        product = next(p for p in (FUTURE, CALL) if p["symbol"] == symbol)
        return {
            "symbol": symbol, "timestamp": int(OPEN.timestamp()) -
            (120 if self.stale else 1),
            "quotes": {"best_bid": "90000", "best_ask": "90001"},
            "product_id": product["id"],
        }

    def place_order(self, *, product, side, size, client_order_id,
                    reduce_only=False):
        if not self.allow_orders:
            raise RuntimeError("Not allowed")
        if self.insufficient_margin:
            raise RuntimeError("Simulated insufficient margin")
        self.trades.append((product["id"], side, size, reduce_only))
        old = self.positions.get(product["id"], 0)
        self.positions[product["id"]] = old + (size if side == "buy" else -size)
        return {"state": "closed", "unfilled_size": 0}

    def order_by_client_id(self, cid):
        return {"state": "closed", "unfilled_size": 0}

    def products(self):
        return [FUTURE, CALL]

    def cancel_product_orders(self, product_id):
        self.pending = [p for p in self.pending if p["product_id"] != product_id]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "bot.jsonl")
        self.now = OPEN
        self.planner = Mock()
        self.planner.propose.return_value = TradePlan(
            "straddle/hedge", "AI research",
            (OrderIntent(1, "buy", 1), OrderIntent(2, "sell", 2)),
        )
        self.exchange = FakeExchange()

    def runner(self, mode="observe"):
        return BotRunner(
            self.exchange, self.planner,
            config=RunnerConfig(mode=mode, journal_path=self.path,
                                ai_interval_seconds=300),
            now=lambda: self.now,
            snapshot_fn=lambda *args, **kwargs: make_snapshot(self.now),
        )

    def test_observe_mode_research_without_orders(self):
        runner = self.runner()
        result = runner.tick()
        self.assertEqual(result["action"], "preview")
        self.assertEqual(result["legs"], 2)
        self.assertEqual(self.exchange.trades, [])
        self.planner.propose.assert_called_once()

    def test_cooldown_avoids_repeated_llm_calls(self):
        runner = self.runner()
        runner.tick()
        self.assertEqual(runner.tick()["action"], "cooldown")
        self.planner.propose.assert_called_once()

    def test_pending_order_blocks_new_proposal(self):
        self.exchange.pending = [{"product_id": 1, "product_symbol": "BTCUSD"}]
        result = self.runner().tick()
        self.assertEqual(result["action"], "pending_orders")
        self.planner.propose.assert_not_called()

    def test_observe_outside_session_raises_exposure_alert(self):
        self.now = WEEKEND
        self.exchange.positions[1] = 3
        with self.assertRaises(ExposureAlert):
            self.runner().tick()
        self.assertEqual(self.exchange.positions[1], 3)
        self.planner.propose.assert_not_called()

    def test_observe_weekend_without_positions(self):
        self.now = WEEKEND
        self.assertEqual(self.runner().tick()["action"], "observed_flat")

    def test_demo_requires_pinned_host_and_order_permission(self):
        with self.assertRaises(RunnerError):
            self.runner("demo")
        self.exchange.allow_orders = True
        self.exchange.base_url = "https://api.india.delta.exchange"
        with self.assertRaises(RunnerError):
            self.runner("demo")

    def test_demo_places_two_legs(self):
        self.exchange.allow_orders = True
        result = self.runner("demo").tick()
        self.assertEqual(result["action"], "demo_order_submitted")
        self.assertEqual(len(self.exchange.trades), 2)
        self.assertEqual(self.exchange.positions, {1: 1, 2: -2})
        self.assertEqual(self.exchange.ticker_reads, 2)

    def test_demo_expired_quote_halts_before_entry(self):
        self.exchange.allow_orders = True
        self.exchange.stale = True
        runner = self.runner("demo")
        with self.assertRaises(RunnerError):
            runner.tick()
        self.assertEqual(self.exchange.trades, [])
        self.assertEqual(runner.tick()["action"], "halted")
        self.planner.propose.assert_called_once()

    def test_demo_margin_rejection_halts_without_false_success(self):
        self.exchange.allow_orders = True
        self.exchange.insufficient_margin = True
        runner = self.runner("demo")
        with self.assertRaises(RunnerError):
            runner.tick()
        self.assertEqual(runner.tick()["action"], "halted")

    def test_demo_flattens_at_session_cutoff_even_without_ai(self):
        self.exchange.allow_orders = True
        self.exchange.positions[1] = 3
        self.now = CLOSEOUT
        result = self.runner("demo").tick()
        self.assertEqual(result["action"], "closeout")
        self.assertEqual(self.exchange.positions[1], 0)
        self.planner.propose.assert_not_called()

    def test_observe_never_flattens_at_cutoff(self):
        self.exchange.positions[1] = 3
        self.now = CLOSEOUT
        with self.assertRaises(ExposureAlert):
            self.runner("observe").tick()
        self.assertEqual(self.exchange.positions[1], 3)

    def test_single_instance_lock_blocks_second_runner(self):
        with SingleInstance(self.path + ".lock"):
            with self.assertRaises(RunnerError):
                with SingleInstance(self.path + ".lock"):
                    pass
        with SingleInstance(self.path + ".lock"):
            pass

    def test_config_invalid_modes(self):
        with self.assertRaises(ValueError):
            RunnerConfig(mode="live")
        with self.assertRaises(ValueError):
            RunnerConfig(ai_interval_seconds=1)


if __name__ == "__main__":
    unittest.main()
