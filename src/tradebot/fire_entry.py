"""Durable, demo-only first-entry submission for a manual Fire press."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from uuid import UUID

from tradebot.delta import DeltaError
from tradebot.fire_probe import validate


class FireEntries:
    def __init__(self, path, exchange):
        self.path = Path(path)
        self.exchange = exchange
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fire_entries (
                press TEXT PRIMARY KEY, status TEXT NOT NULL, receipt TEXT NOT NULL)""")

    def _receipt(self, db, press):
        row = db.execute("SELECT receipt FROM fire_entries WHERE press=?", (press,)).fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, db, receipt):
        db.execute("INSERT OR REPLACE INTO fire_entries VALUES (?, ?, ?)",
                   (receipt["press"], receipt["status"], json.dumps(receipt)))
        db.commit()
        return receipt

    def submit_first_entry(self, press_id, snapshot, decision):
        press = UUID(press_id).hex
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._receipt(db, press)
            if previous:
                return previous
            if db.execute("SELECT 1 FROM fire_entries WHERE status IN ('submitting','unconfirmed','accepted')").fetchone():
                raise DeltaError("Previous entry requires exchange reconciliation")
            core = snapshot["core"]
            ticker = core["ticker"]
            if (snapshot["environment"] != "delta-india-demo" or ticker["symbol"] != "BTCUSD"
                    or ticker["contract_type"] != "perpetual_futures"):
                raise DeltaError("Expected Delta India demo BTCUSD perpetual")
            plan = validate(decision, core)
            product_id = ticker["product_id"]
            if type(product_id) is not int or product_id <= 0:
                raise DeltaError("Invalid BTCUSD product ID")
            positions = self.exchange.btc_positions()
            if snapshot["position_contracts"] or any(int(p["size"]) for p in positions
                                                      if str(p["product_id"]) == str(product_id)):
                raise DeltaError("First-entry submission requires a flat BTCUSD position")
            receipt = dict(press=press, product_id=product_id, plan=plan, status="submitting")
            self._save(db, receipt)
            try:
                result = self.exchange._request("POST", "/v2/orders", auth=True, payload={
                    "product_id": product_id, "client_order_id": press,
                    "side": "buy" if plan["direction"] == "LONG" else "sell",
                    "size": plan["contracts"], "order_type": "market_order",
                    "bracket_stop_loss_price": plan["stop_loss"],
                    "bracket_take_profit_price": plan["take_profit"],
                })["result"]
                self._apply_result(receipt, result)
            except (DeltaError, OSError, ValueError, TypeError, KeyError):
                receipt["status"] = "unconfirmed"
            db.execute("BEGIN IMMEDIATE")
            latest = self._receipt(db, press)
            if latest["status"] != "submitting":
                return latest
            return self._save(db, receipt)

    @staticmethod
    def _apply_result(receipt, order):
        if (not isinstance(order, dict) or order.get("client_order_id") != receipt["press"]
                or order.get("product_id") != receipt["product_id"] or not order.get("id")):
            raise DeltaError("Order identity unconfirmed")
        receipt["order_id"] = order["id"]
        receipt["exchange_state"] = order.get("state")
        if order.get("state") == "closed" and str(order.get("unfilled_size")) == "0":
            receipt["status"] = "filled"
        elif order.get("state") == "cancelled":
            receipt["status"] = "cancelled"
        else:
            receipt["status"] = "accepted"

    def reconcile(self, press_id):
        press = UUID(press_id).hex
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = self._receipt(db, press)
            if receipt is None or receipt["status"] in ("filled", "cancelled"):
                return receipt
            order = self.exchange.order_by_client_id(press)
            self._apply_result(receipt, order)
            return self._save(db, receipt)
