"""Read-only, exchange-observed position lifecycle and durable fill history."""
import json
import time
from decimal import Decimal, InvalidOperation
from .execution import product_for
from .broker import error_detail

POSITION_FIELDS = ("product_id", "product_symbol", "size", "entry_price", "margin",
                   "liquidation_price", "mark_price", "margin_mode", "unrealized_pnl",
                   "realized_pnl", "realized_cashflow", "realized_funding", "commission",
                   "created_at", "updated_at")
ORDER_FIELDS = ("id", "client_order_id", "product_id", "side", "size", "unfilled_size",
                "state", "average_fill_price", "stop_order_type", "stop_price",
                "bracket_order", "reduce_only", "created_at", "updated_at", "paid_commission","stop_trigger_method","cancellation_reason")
FILL_FIELDS = ("id", "order_id", "product_id", "product_symbol", "side", "size",
               "price", "commission", "settling_asset_symbol", "fill_type", "created_at")
NEW_POSITION_FIELDS = ("size", "margin", "entry_price", "realized_pnl",
                       "realized_cashflow", "realized_funding", "total_commission_paid")
def select(row, keys):
    return {k: row[k] for k in keys if k in row}

def decimal(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError):
        return None

def same_product(row, pid):
    return isinstance(row, dict) and str(row.get("product_id")) == str(pid)

def pages(fetch, pid, limit=5):
    rows, cursor, seen = [], None, set()
    for _ in range(limit):
        envelope = fetch(pid, cursor)
        batch = envelope["result"]
        if not isinstance(batch, list):
            raise ValueError("Expected paginated list")
        rows.extend(row for row in batch if same_product(row, pid))
        cursor = envelope.get("meta", {}).get("after")
        if not cursor:
            return rows, True
        if cursor in seen:
            raise ValueError("Repeated exchange cursor")
        seen.add(cursor)
    return rows, False

def normalize_fill(row):
    ident = row.get("id")
    if ident is None or isinstance(ident, bool) or not str(ident):
        raise ValueError("Missing exchange fill id")
    out = select(row, FILL_FIELDS)
    new_position = (row.get("meta_data") or {}).get("new_position")
    if isinstance(new_position, dict):
        out["new_position"] = select(new_position, NEW_POSITION_FIELDS)
        # Flat after this fill, not proof that any particular AI entry closed.
        if decimal(new_position.get("size")) == 0:
            out["position_flat_after_fill"] = True
    return str(ident), out

def order_state(row):
    size, remaining = decimal(row.get("size")), decimal(row.get("unfilled_size"))
    state = row.get("state")
    filled = None
    if size is not None and remaining is not None and 0 <= remaining <= size:
        filled = str(size - remaining)
    if state in ("cancelled", "canceled"):
        status = "cancelled_partial" if filled is not None and decimal(filled) > 0 else "cancelled"
    elif size is not None and size > 0 and remaining == 0 and state == "closed":
        status = "filled"
    elif filled is not None and decimal(filled) > 0 and remaining > 0:
        status = "partial"
    elif state in ("open", "pending"):
        status = state
    else:
        status = "unverified"
    return {"status": status, "filled_size": filled, "order": select(row, ORDER_FIELDS)}

def bracket_evidence(positions, orders, complete):
    if not positions:
        return "no_position"
    if not complete:
        return "unverified_incomplete_orders"
    # Position-level observation only, not attribution or coverage verification.
    signs = [decimal(p.get("size")) for p in positions]
    if len(signs) != 1 or signs[0] is None or signs[0] == 0:
        return "unverified_position"
    side = "sell" if signs[0] > 0 else "buy"
    types = {o.get("stop_order_type") for o in orders
             if o.get("state") in ("open", "pending") and o.get("side") == side
             and (o.get("reduce_only") is True or o.get("bracket_order") is True)
             and decimal(o.get("stop_price")) is not None
             and decimal(o.get("stop_price")) > 0}
    return ("both_legs_observed" if {"stop_loss_order", "take_profit_order"} <= types
            else "missing_leg_evidence")

class Lifecycle:
    def __init__(self, broker, journal):
        self.broker, self.journal = broker, journal
        self.db = journal.db
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS lifecycle_snapshots (
                id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, observed INTEGER NOT NULL,
                detail TEXT NOT NULL)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS observed_fills (
                symbol TEXT NOT NULL, fill_id TEXT NOT NULL, detail TEXT NOT NULL,
                PRIMARY KEY(symbol, fill_id))""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS observed_orders (
                client_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, observed INTEGER NOT NULL,
                detail TEXT NOT NULL)""")

    def refresh(self, symbol):
        pid = product_for(self.broker, symbol)["id"]
        now = int(time.time())
        result, errors = {}, {}
        def collect(name, fn):
            try:
                result[name] = fn()
            except Exception as exc:
                errors[name] = type(exc).__name__
        def positions():
            rows = self.broker.margined_positions(pid)
            if not isinstance(rows, list):
                raise ValueError("Expected position list")
            selected = [select(p, POSITION_FIELDS) for p in rows if same_product(p, pid)]
            if any(decimal(p.get("size")) is None for p in selected):
                raise ValueError("Missing position size")
            return [p for p in selected if decimal(p["size"]) != 0]
        def wallet():
            envelope = self.broker.wallet()
            rows = envelope["result"]
            if not isinstance(rows, list):
                raise ValueError("Expected wallet list")
            return [select(row, ("asset_symbol", "balance", "available_balance",
                                 "position_margin", "order_margin")) for row in rows]
        collect("wallets", wallet)
        collect("positions", positions)
        collect("active_orders", lambda: pages(self.broker.active_orders_page, pid))
        collect("fills", lambda: pages(self.broker.fills_page, pid))
        new_fills = 0
        if "fills" in result:
            fills, fill_complete = result.pop("fills")
            with self.db:
                for row in fills:
                    try:
                        ident, detail = normalize_fill(row)
                    except ValueError:
                        errors["fill_schema"] = "InvalidFill"
                        continue
                    new_fills += self.db.execute(
                        "INSERT OR IGNORE INTO observed_fills VALUES (?,?,?)",
                        (symbol, ident, json.dumps(detail, allow_nan=False))).rowcount
            result["fill_window_complete"] = fill_complete and "fill_schema" not in errors
        if "active_orders" in result:
            orders, complete = result["active_orders"]
            result["active_orders"] = [select(o, ORDER_FIELDS) for o in orders]
            result["active_orders_complete"] = complete
            if "positions" in result:
                result["bracket_evidence"] = bracket_evidence(result["positions"], orders, complete)
        result.setdefault("bracket_evidence", "unverified")
        # Track unresolved and acknowledged entries until exchange reports a terminal state.
        pending = self.db.execute("""SELECT o.client_id FROM orders o
             WHERE o.symbol=? AND o.status IN ('submitting','unknown','acknowledged')
             ORDER BY o.rowid DESC""", (symbol,)).fetchall()
        checked = 0
        lookup_diagnostics = {}
        for (client_id,) in pending:
            old = self.db.execute("SELECT detail FROM observed_orders WHERE client_id=?",
                                  (client_id,)).fetchone()
            if old and json.loads(old[0])["status"] in ("filled","cancelled","cancelled_partial"):
                continue
            if checked >= 25:
                errors["order_poll"] = "BatchLimit"
                break
            checked += 1
            try:
                row = self.broker.order(client_id)
                if not same_product(row, pid) or row.get("client_order_id") != client_id:
                    raise ValueError("Order identity mismatch")
                detail = order_state(row)
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO observed_orders VALUES (?,?,?,?)",
                                    (client_id, symbol, now, json.dumps(detail, allow_nan=False)))
            except Exception as exc:
                errors["order_poll"] = type(exc).__name__
                lookup_diagnostics[client_id] = error_detail(exc)
        result.update({"symbol": symbol, "observed": now, "errors": errors,
                       "new_fills": new_fills, "orders_checked": checked,
                       "order_lookup_diagnostics": lookup_diagnostics})
        with self.db:
            self.db.execute("INSERT INTO lifecycle_snapshots(symbol,observed,detail) VALUES (?,?,?)",
                            (symbol, now, json.dumps(result, allow_nan=False)))
        return result
