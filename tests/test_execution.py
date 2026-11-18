import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tradebot.ai import OrderIntent, TradePlan
from tradebot.execution import CloseoutError, DemoExecutor, ExecutionError, SessionController
from tradebot.session import SessionPhase

IST = ZoneInfo("Asia/Kolkata")
FUTURE = {"id": 1, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
          "state": "live"}
CALL = {"id": 2, "symbol": "C-BTC-90000-271126", "contract_type": "call_options",
        "state": "live"}
ETH = {"id": 3, "symbol": "ETHUSD", "contract_type": "perpetual_futures",
       "state": "live"}
PRODUCTS = [FUTURE, CALL, ETH]


class FakeExchange:
    def __init__(self):
        self.positions = {}
        self.orders = []
        self.open_pending = []
        self.calls = []
        self.fail_after = None
        self.unclear_closes = False

    def products(self):
        return PRODUCTS

    def btc_positions(self):
        return [
            {"product_id": pid, "product_symbol": (FUTURE if pid == 1 else CALL)["symbol"],
             "size": size}
            for pid, size in self.positions.items() if size
        ]

    def open_orders(self):
        return list(self.open_pending)

    def cancel_product_orders(self, product_id):
        self.calls.append(("cancel", product_id))
        self.open_pending = [o for o in self.open_pending
                             if o["product_id"] != product_id]

    def place_order(self, *, product, side, size, client_order_id, reduce_only=False):
        self.calls.append(("order", product["id"], side, size, reduce_only))
        if self.fail_after is not None and len([c for c in self.calls if c[0] == "order"]) > self.fail_after:
            raise RuntimeError("Simulated exchange rejected leg")
        pid = product["id"]
        old = self.positions.get(pid, 0)
        delta = size if side == "buy" else -size
        if not (self.unclear_closes and reduce_only):
            new = old + delta
            if reduce_only and abs(new) > abs(old):
                raise RuntimeError("Reduce only would enlarge position")
            self.positions[pid] = new
        self.orders.append({"client_order_id": client_order_id,
                            "state": "closed", "unfilled_size": 0})
        return self.orders[-1]

    def order_by_client_id(self, client_order_id):
        return next(o for o in self.orders if o["client_order_id"] == client_order_id)


class TestExecution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exchange = FakeExchange()
        self.now = datetime(2026, 11, 17, 21, 0, tzinfo=IST)
        self.engine = DemoExecutor(
            self.exchange,
            journal_path=str(Path(self.tmp.name) / "history.jsonl"),
            now=lambda: self.now,
            pause=lambda _: None,
        )

    def test_multileg_submits_and_later_flattens(self):
        plan = TradePlan("AI volatility hedge", "Research test",
                         (OrderIntent(1, "buy", 4), OrderIntent(2, "sell", 3)))
        report = self.engine.execute(plan, PRODUCTS)
        self.assertEqual(len(report.submitted_client_ids), 2)
        self.assertEqual(self.exchange.positions, {1: 4, 2: -3})
        self.engine.closeout()
        self.assertFalse(any(self.exchange.positions.values()))
        self.assertEqual(
            len([c for c in self.exchange.calls if c[0] == "order" and c[4]]), 2)

    def test_no_entry_during_flatten_phase(self):
        self.now = datetime(2026, 11, 18, 2, 20, tzinfo=IST)
        plan = TradePlan("Long futures", "Research", (OrderIntent(1, "buy", 1),))
        with self.assertRaises(ExecutionError):
            self.engine.execute(plan, PRODUCTS)
        self.assertFalse(self.exchange.calls)

    def test_no_entry_on_market_holiday(self):
        self.now = datetime(2026, 11, 26, 20, 0, tzinfo=IST)
        with self.assertRaises(ExecutionError):
            self.engine.execute(TradePlan("X", "Y", (OrderIntent(1, "buy", 1),)), PRODUCTS)

    def test_partial_failure_attempts_unwind(self):
        self.exchange.fail_after = 1
        plan = TradePlan("spread", "research",
                         (OrderIntent(1, "buy", 4), OrderIntent(2, "sell", 2)))
        with self.assertRaises(CloseoutError):
            self.engine.execute(plan, PRODUCTS)
        # Simulated exchange refuses all subsequent orders, so exposure remains.
        self.assertEqual(self.exchange.positions[1], 4)

    def test_open_btc_orders_cancelled_not_eth(self):
        self.exchange.open_pending = [
            {"product_symbol": "BTCUSD", "product_id": 1},
            {"product_symbol": "ETHUSD", "product_id": 3},
        ]
        self.engine.closeout()
        self.assertEqual(len(self.exchange.open_pending), 1)
        self.assertEqual(self.exchange.open_pending[0]["product_symbol"], "ETHUSD")

    def test_unknown_open_order_prevents_false_flat_confirmation(self):
        # Missing symbol could represent a BTC order. Never claim all flat.
        self.exchange.open_pending = [{"product_id": 1}]
        with self.assertRaises(CloseoutError):
            self.engine.closeout(max_attempts=1)

    def test_closeout_requires_real_position_verification(self):
        self.exchange.positions[1] = -5
        self.exchange.unclear_closes = True
        with self.assertRaises(CloseoutError):
            self.engine.closeout(max_attempts=2)
        self.assertEqual(self.exchange.positions[1], -5)

    def test_closeout_retries_late_after_early_close(self):
        self.now = datetime(2026, 11, 27, 23, 30, tzinfo=IST)
        self.exchange.positions[1] = 2
        phase = SessionController(self.engine).tick()
        self.assertEqual(phase, SessionPhase.CLOSED)
        self.assertEqual(self.exchange.positions[1], 0)

    def test_ai_cannot_send_eth(self):
        with self.assertRaises(ExecutionError):
            self.engine.execute(
                TradePlan("Wrong asset", "test", (OrderIntent(3, "buy", 1),)),
                PRODUCTS)
        self.assertFalse(self.exchange.calls)


if __name__ == "__main__":
    unittest.main()
