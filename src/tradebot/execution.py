"""Exchange-facing entry and compulsory closeout.

No model can bypass these mechanical guards through this execution interface.
Multi-leg strategies are NOT atomic on Delta. A partial failure triggers a
BTC-only unwind attempt; any unclosed exposure produces an exception/alert.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from time import sleep
from uuid import uuid4

from tradebot.ai import TradePlan
from tradebot.delta import is_btc_contract
from tradebot.journal import record
from tradebot.session import SessionPhase, session_phase


class ExecutionError(RuntimeError):
    pass


class CloseoutError(ExecutionError):
    pass


@dataclass(frozen=True)
class ExecutionReport:
    strategy: str
    submitted_client_ids: tuple[str, ...]


def _btc_symbol(symbol: str) -> bool:
    symbol = str(symbol or "").upper()
    return symbol.startswith(("BTC", "C-BTC-", "P-BTC-"))


def _position_size(pos: dict) -> int:
    try:
        value = Decimal(str(pos["size"]))
        if not value.is_finite() or value != int(value):
            raise ValueError
        return int(value)
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        raise CloseoutError("Invalid contract size in position response") from exc


class DemoExecutor:
    """Serialized *per-process* execution; deploy just one process per demo account.

    Do not connect a real account. A separate scheduler must invoke closeout
    continuously during FLATTEN and keep retrying after session close.
    """

    def __init__(self, exchange, *, journal_path: str = "data/trades.jsonl",
                 now=None, pause=None):
        self.exchange = exchange
        self.journal_path = journal_path
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.pause = pause or sleep

    def _log(self, kind: str, info: dict):
        record(self.journal_path, kind, info)

    def execute(self, plan: TradePlan, products: list[dict]) -> ExecutionReport:
        if session_phase(self.now()) != SessionPhase.TRADING:
            raise ExecutionError("New positions are forbidden outside NYSE entry window")
        ids_to_products = {int(p["id"]): p for p in products if is_btc_contract(p)}
        if not plan.orders:
            self._log("wait", {"strategy": plan.strategy, "rationale": plan.rationale})
            return ExecutionReport(plan.strategy, ())
        for leg in plan.orders:
            if (type(leg.product_id) is not int or leg.product_id not in ids_to_products
                    or leg.side not in ("buy", "sell")
                    or type(leg.size) is not int or leg.size < 1):
                raise ExecutionError("Invalid AI leg rejected before placing any order")
        submitted = []
        try:
            for leg in plan.orders:
                if session_phase(self.now()) != SessionPhase.TRADING:
                    raise ExecutionError("Session cutoff crossed during multi-leg entry")
                cid = "tb2-" + uuid4().hex[:24]
                self.exchange.place_order(product=ids_to_products[leg.product_id],
                                          side=leg.side, size=leg.size,
                                          client_order_id=cid)
                submitted.append(cid)
                status = self.exchange.order_by_client_id(cid)
                if status.get("state") != "closed" or int(status.get("unfilled_size", 0)):
                    raise ExecutionError(f"Order fill not verified for client ID {cid}")
                self._log("entry_filled", {"client_order_id": cid,
                                          "product_id": leg.product_id,
                                          "side": leg.side, "size": leg.size,
                                          "strategy": plan.strategy})
            return ExecutionReport(plan.strategy, tuple(submitted))
        except Exception as exc:
            self._log("entry_failure", {"strategy": plan.strategy,
                                        "error_type": type(exc).__name__})
            try:
                self.closeout()
            except Exception as close_exc:
                raise CloseoutError(
                    "Entry failure; attempted BTC unwind but flatness is NOT confirmed"
                ) from close_exc
            raise ExecutionError("Entry failed; BTC closeout verified") from exc

    def closeout(self, *, max_attempts: int = 5) -> None:
        """Cancel BTC pending orders, reduce BTC positions and verify flat.

        Never claim completion if orders remain, positions persist or the
        exchange fails. Use a dedicated demo account; another bot must not trade
        the same account concurrently.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        failures = []
        for attempt in range(max_attempts):
            try:
                open_orders = self.exchange.open_orders()
                btc_open = [o for o in open_orders if _btc_symbol(o.get("product_symbol"))]
                for product_id in sorted({int(o["product_id"]) for o in btc_open}):
                    self.exchange.cancel_product_orders(product_id)

                positions = [p for p in self.exchange.btc_positions()
                             if _position_size(p) != 0]
                if positions:
                    products = {int(p["id"]): p for p in self.exchange.products()
                                if is_btc_contract(p)}
                    for position in positions:
                        pid = int(position["product_id"])
                        size = _position_size(position)
                        product = products.get(pid)
                        if product is None:
                            failures.append(f"BTC product {pid} is not tradeable")
                            continue
                        side = "sell" if size > 0 else "buy"
                        cid = "tb2-exit-" + uuid4().hex[:20]
                        self.exchange.place_order(
                            product=product, side=side, size=abs(size),
                            client_order_id=cid, reduce_only=True)
                        self._log("exit_submitted", {"product_id": pid,
                                                    "contracts": abs(size), "side": side,
                                                    "attempt": attempt + 1})
                # Verify using fresh remote state; request acceptance != filled.
                remaining = [p for p in self.exchange.btc_positions()
                             if _position_size(p) != 0]
                pending = [o for o in self.exchange.open_orders()
                           if _btc_symbol(o.get("product_symbol"))]
                if not remaining and not pending:
                    self._log("btc_flat_verified", {"attempt": attempt + 1})
                    return
                failures.append(f"attempt {attempt + 1}: "
                                f"{len(remaining)} positions, {len(pending)} pending orders")
            except Exception as exc:
                failures.append(f"attempt {attempt + 1}: {type(exc).__name__}")
            if attempt < max_attempts - 1:
                self.pause(1)
        self._log("closeout_alert", {"attempts": max_attempts,
                                     "recent_errors": failures[-3:]})
        raise CloseoutError(
            "BTC exposure or pending orders not verified flat; "
            "requires immediate manual review: " + "; ".join(failures[-3:])
        )


class SessionController:
    """Invoke tick regularly even when AI is unavailable or a session ends."""

    def __init__(self, executor: DemoExecutor):
        self.executor = executor

    def tick(self) -> SessionPhase:
        phase = session_phase(self.executor.now())
        if phase != SessionPhase.TRADING:
            # Also retries after official close; an exchange outage must not
            # turn an unverified position into a false 'session complete'.
            self.executor.closeout()
        return phase
