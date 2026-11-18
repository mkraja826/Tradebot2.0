"""Optional 24x7 read-only BTCUSD position watcher and Kimi research triggers.

No GPT-6 decisions or Delta order mutations happen here. Starts with no
paid-model calls. Operator must opt into paid Kimi reviews separately.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.kimi_learning import KimiLearningReviewer
from tradebot.market import _age_seconds
from tradebot.trade_memory import TradeMemory


class LearningWatchError(ValueError):
    pass


def _positive_number(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError
        return number
    except (TypeError, ValueError, InvalidOperation):
        raise LearningWatchError("Invalid BTC market price") from None


def _position_size(position):
    try:
        number = Decimal(str(position["size"]))
        if not number.is_finite() or int(number) != number:
            raise ValueError
        return int(number)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise LearningWatchError("Malformed signed BTC position") from None


class LearningWatcher:
    """Observes broker facts; on_review is optional and receives only IDs."""

    def __init__(self, exchange, memory, *, on_review=None, now=None):
        if (getattr(exchange, "base_url", None) != DEMO_API or
                getattr(exchange, "allow_orders", None) is not False):
            raise LearningWatchError("Learning watcher must use read-only Delta India DEMO")
        self.exchange = exchange
        self.memory = memory
        self.on_review = on_review
        self.now = now or (lambda: datetime.now(timezone.utc))

    def poll(self):
        now = self.now()
        if now.tzinfo is None:
            raise LearningWatchError("Watcher requires timezone-aware clock")
        timestamp = now.isoformat()

        # Signed GET only. Incomplete reads throw; NEVER convert an outage to
        # an empty position, because that would fabricate a trade exit.
        ticker = self.exchange.ticker("BTCUSD")
        positions = self.exchange.btc_positions()
        orders = self.exchange.open_orders()
        if (not isinstance(ticker, dict) or ticker.get("symbol") != "BTCUSD" or
                not isinstance(positions, list) or not isinstance(orders, list)):
            raise LearningWatchError("Incomplete Delta Demo account evidence")
        if _age_seconds(ticker.get("timestamp"), now) > 60:
            raise LearningWatchError("Stale BTC quote; refusing to record position change")
        quotes = ticker.get("quotes")
        if not isinstance(quotes, dict):
            raise LearningWatchError("Missing quote")
        bid, ask = _positive_number(quotes.get("best_bid")), _positive_number(quotes.get("best_ask"))
        if bid >= ask:
            raise LearningWatchError("Crossed or locked quote")
        mark = _positive_number(ticker.get("mark_price"))
        product_id = ticker.get("product_id")
        if type(product_id) is not int or product_id <= 0:
            raise LearningWatchError("Missing BTCUSD product identity")

        matching = []
        for row in positions:
            if not isinstance(row, dict):
                raise LearningWatchError("Malformed position list")
            # An absent product ID is ambiguous, never treated as no exposure.
            if "product_id" not in row:
                raise LearningWatchError("BTC position lacks product ID")
            if str(row["product_id"]) == str(product_id):
                matching.append(row)
        if len(matching) > 1:
            raise LearningWatchError("Multiple BTCUSD positions cannot be reconciled")
        position = matching[0] if matching else None
        size = _position_size(position) if position is not None else 0

        previous = self.memory.watch_state()
        previous_active = bool(previous and previous["active"])
        prior_id = previous["trade_id"] if previous_active else None
        if size == 0:
            if previous_active and orders:
                return {"status": "flat_with_pending_orders_unverified",
                        "trade_id": prior_id, "orders": len(orders)}
            if previous_active:
                self.memory.append_event(
                    prior_id, "position_closed_observed", {
                        "symbol": "BTCUSD", "product_id": product_id,
                        "prior_size": previous["last_size"], "mark_price": str(mark),
                        "bid": str(bid), "ask": str(ask),
                        "observed_at": timestamp, "realized_pnl_verified": False,
                    })
                self.memory.save_watch_state(
                    trade_id=None, active=False, size=0, mark=mark, observed_at=timestamp)
                self._notify(prior_id, "exit", "exit-" + prior_id)
                return {"status": "flat_observed_not_pnl_verified", "trade_id": prior_id}
            self.memory.save_watch_state(
                trade_id=None, active=False, size=0, mark=mark, observed_at=timestamp)
            return {"status": "flat_idle", "orders": len(orders)}

        if previous_active and int(previous["last_size"]) * size < 0:
            # A reversal may combine an exit and an entry: never silently
            # assume any particular fills or realize P&L.
            self.memory.append_event(prior_id, "exchange_uncertain", {
                "reason": "Position direction reversed; broker fills require reconciliation",
                "observed_at": timestamp,
            })
            previous_active = False

        trade_id = prior_id if previous_active else "btc-" + uuid4().hex
        if not previous_active:
            self.memory.append_event(trade_id, "position_first_observed", {
                "symbol": "BTCUSD", "product_id": product_id,
                "size": str(size), "entry_price": str(position.get("entry_price") or ""),
                "mark_price": str(mark), "bid": str(bid), "ask": str(ask),
                "observed_at": timestamp,
            })
            self.memory.save_watch_state(
                trade_id=trade_id, active=True, size=size, mark=mark, observed_at=timestamp,
                review_mark=mark, review_at=timestamp)
            self._notify(trade_id, "entry", "entry-" + trade_id)
            return {"status": "active_first_observed", "trade_id": trade_id,
                    "size": size, "paid_review_possible": bool(self.on_review)}

        try:
            last_review = datetime.fromisoformat(previous["last_review_at"])
            elapsed = (now - last_review).total_seconds()
        except (ValueError, TypeError):
            elapsed = 1800
        previous_mark = _positive_number(previous["last_review_mark"] or previous["last_mark"])
        delta = abs(mark - previous_mark) / previous_mark
        changed_size = str(size) != previous["last_size"]
        due_review = (delta >= Decimal("0.006") or elapsed >= 1800)
        if due_review or changed_size:
            self.memory.append_event(trade_id, "position_observed", {
                "symbol": "BTCUSD", "product_id": product_id,
                "size": str(size), "entry_price": str(position.get("entry_price") or ""),
                "mark_price": str(mark), "bid": str(bid), "ask": str(ask),
                "observed_at": timestamp,
            })
        self.memory.save_watch_state(
            trade_id=trade_id, active=True, size=size, mark=mark, observed_at=timestamp,
            review_mark=mark if due_review else previous["last_review_mark"],
            review_at=timestamp if due_review else previous["last_review_at"])
        if due_review:
            # At most one review per 30-minute UTC bucket (and global daily budget).
            review_key = "checkpoint-" + trade_id + "-" + str(int(now.timestamp()) // 1800)
            self._notify(trade_id, "checkpoint", review_key)
        return {"status": "active", "trade_id": trade_id,
                "size": size, "checkpoint": due_review}

    def _notify(self, trade_id, phase, review_key):
        if self.on_review is not None:
            self.on_review(trade_id, phase, review_key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true",
                        help="Poll continuously; default is one read-only observation")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--paid-kimi", action="store_true",
                        help="Explicitly enable model-credit-consuming Kimi trade reviews")
    parser.add_argument("--database", default="data/trade-learning.sqlite")
    args = parser.parse_args(argv)
    if args.interval < 10 or args.interval > 300:
        parser.error("--interval must be 10..300 seconds")

    exchange = DeltaDemo(api_key=os.environ.get("DELTA_DEMO_API_KEY", ""),
                         api_secret=os.environ.get("DELTA_DEMO_API_SECRET", ""),
                         allow_orders=False)
    memory = TradeMemory(args.database)
    reviewer = KimiLearningReviewer(memory)
    # The single worker keeps read-only broker polling independent of paid AI
    # latency. It cannot submit orders and model calls are capped by SQLite.
    with ThreadPoolExecutor(max_workers=1) as pool:
        callback = (
            (lambda trade_id, phase, key: pool.submit(
                reviewer.review, trade_id, phase, key))
            if args.paid_kimi else None
        )
        watcher = LearningWatcher(exchange, memory, on_review=callback)
        while True:
            try:
                output = watcher.poll()
            except Exception as exc:
                # Do not display upstream broker contents or auth details.
                output = {"status": "broker_evidence_unavailable",
                          "error_type": type(exc).__name__, "orders_submitted": False}
            output["kimi_paid_enabled"] = args.paid_kimi
            # Non-secret atomic heartbeat for dashboard visibility. A stale
            # heartbeat cannot be presented as evidence that Kimi is running.
            runtime_path = Path(args.database).resolve().parent / "learning-runtime.json"
            tmp = runtime_path.with_name(runtime_path.name + "." + str(os.getpid()) + ".tmp")
            try:
                with os.fdopen(os.open(
                    str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600
                ), "w", encoding="utf-8") as out:
                    json.dump({
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "watcher_status": output["status"],
                        "kimi_paid_enabled": args.paid_kimi,
                        "orders_submitted": False,
                    }, out, separators=(",", ":"))
                os.replace(tmp, runtime_path)
            except OSError:
                pass
            print(json.dumps(output, separators=(",", ":")), flush=True)
            if not args.watch:
                break
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
