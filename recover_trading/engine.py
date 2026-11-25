"""Strategy-independent demo execution and durable decision journal."""
import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class OrderIntent:
    product_id: int
    side: str
    size: int
    reduce_only: bool = False

    def __post_init__(self):
        if type(self.product_id) is not int or self.product_id < 1:
            raise ValueError("Invalid exchange product id")
        if self.side not in ("buy", "sell"):
            raise ValueError("Invalid exchange order side")
        if type(self.size) is not int or self.size < 1:
            raise ValueError("Exchange requires a positive integer contract size")
        if type(self.reduce_only) is not bool:
            raise ValueError("Invalid reduce_only")


class Strategy(Protocol):
    def decide(self, symbol: str, ticker: dict) -> OrderIntent | None: ...


class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS orders (
            client_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, intent TEXT NOT NULL,
            status TEXT NOT NULL, detail TEXT)""")
        self.db.commit()

    def begin(self, client_id, symbol, intent):
        with self.db:
            self.db.execute("INSERT INTO orders VALUES (?, ?, ?, ?, NULL)",
                            (client_id, symbol, json.dumps(asdict(intent)), "submitting"))

    def finish(self, client_id, status, detail):
        with self.db:
            self.db.execute("UPDATE orders SET status=?, detail=? WHERE client_id=?",
                            (status, json.dumps(detail), client_id))

    def unresolved(self):
        return [row[0] for row in self.db.execute(
            "SELECT client_id FROM orders WHERE status IN ('submitting','unknown')")]

    def close(self):
        self.db.close()


class Engine:
    def __init__(self, broker, strategy: Strategy, journal: Journal):
        self.broker, self.strategy, self.journal = broker, strategy, journal

    def tick(self, symbol):
        ticker = self.broker.ticker(symbol)
        intent = self.strategy.decide(symbol, ticker)
        if intent is None:
            return None
        if not isinstance(intent, OrderIntent):
            raise TypeError("Strategy must return OrderIntent or None")
        # The strategy supplies the order, without equity or loss admission logic.
        # Persist the unique id before calling the broker; never replay on timeout.
        client_id = uuid4().hex
        self.journal.begin(client_id, symbol, intent)
        try:
            result = self.broker.submit(intent, client_id)
        except Exception as exc:
            self.journal.finish(client_id, "unknown", {"error": type(exc).__name__})
            raise
        self.journal.finish(client_id, "acknowledged", result)
        return result

    def reconcile(self):
        """Look up ambiguous submissions without repeating them."""
        for client_id in self.journal.unresolved():
            try:
                result = self.broker.order(client_id)
            except Exception:
                continue
            if isinstance(result, dict) and result.get("id") is not None:
                self.journal.finish(client_id, "acknowledged", result)
