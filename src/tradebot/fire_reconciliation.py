"""Read-only, as-of-cutoff accounting for isolated Delta Demo FIRE round trips.

Order IDs establish ownership; complete fills establish quantities and flat
boundaries; wallet postings establish actual cash movements. Ambiguity never
becomes zero profit. No model, order mutation, or trading setting is used here.
"""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from tradebot.delta import DEMO_API
from tradebot.fire_market import SYMBOLS

VERSION = "fire-reconciliation-v1"
ZERO = Decimal(0)
US = 1_000_000
EXTERNAL = frozenset({"deposit", "withdrawal", "withdrawal_cancellation",
    "external_deposit", "sub_account_transfer", "conversion", "fund_deposit",
    "fund_withdrawal", "fund_wallet_deposit", "fund_wallet_withdrawal"})


class ReconciliationError(ValueError):
    """Only fixed reason codes, never upstream payloads."""


def require(condition, reason):
    if not condition:
        raise ReconciliationError(reason)


def number(value):
    try:
        require(type(value) in (str, int, Decimal), "invalid_numeric_evidence")
        result = Decimal(value)
        require(result.is_finite(), "invalid_numeric_evidence")
        require(len(result.as_tuple().digits) <= 36 and -24 <= result.as_tuple().exponent <= 24
                and result.adjusted() <= 24, "invalid_numeric_evidence")
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ReconciliationError("invalid_numeric_evidence") from None


def identifier(value):
    require(type(value) in (str, int) and 0 < len(str(value)) <= 96
            and all(c.isalnum() or c in "-_" for c in str(value)), "invalid_evidence_id")
    return str(value)


def timestamp_us(value):
    """Broker microseconds or explicit timezone-aware ISO; no guessed units."""
    if type(value) is int or (isinstance(value, str) and value.isdigit()):
        result = int(value)
        require(10**14 <= result < 10**17, "invalid_evidence_timestamp")
        return result
    try:
        stamp = datetime.fromisoformat(value)
        require(stamp.tzinfo is not None, "invalid_evidence_timestamp")
        delta = stamp.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        result = (delta.days * 86400 + delta.seconds) * US + delta.microseconds
        require(result > 0, "invalid_evidence_timestamp")
        return result
    except (TypeError, ValueError):
        raise ReconciliationError("invalid_evidence_timestamp") from None


def decimal_text(value):
    value = number(value)
    text = format(value, "f")
    return "0" if not value else text.rstrip("0").rstrip(".") if "." in text else text


def normalize_fill(raw):
    product = raw.get("product") or {}
    meta = raw.get("meta_data") or {}
    require(isinstance(meta, dict), "invalid_fill_metadata")
    position = meta.get("new_position") or {}
    require(isinstance(product, dict) and isinstance(position, dict), "invalid_fill_metadata")
    row = {"id": identifier(raw.get("id")), "order_id": identifier(raw.get("order_id")),
           "product_id": identifier(raw.get("product_id")), "symbol": raw.get("product_symbol"),
           "at_us": timestamp_us(raw.get("created_at")), "side": raw.get("side"),
           "size": decimal_text(raw.get("size")), "price": decimal_text(raw.get("price")),
           "commission": decimal_text(raw.get("commission")),
           "asset": raw.get("settling_asset_symbol"), "fill_type": raw.get("fill_type"),
           "position_after": decimal_text(position["size"]) if "size" in position else None,
           "realized_funding": decimal_text(position["realized_funding"])
               if position.get("realized_funding") is not None else None,
           "contract_value": decimal_text(product["contract_value"])
               if product.get("contract_value") is not None else None,
           "notional_type": product.get("notional_type")}
    require(row["symbol"] in SYMBOLS and row["side"] in ("buy", "sell"), "invalid_fill_market")
    require(number(row["size"]) > 0 and number(row["size"]) == number(row["size"]).to_integral_value()
            and number(row["price"]) > 0, "invalid_fill_quantity_or_price")
    require(isinstance(row["asset"], str) and row["asset"], "missing_settlement_asset")
    if product:
        require(str(product.get("id")) == row["product_id"]
                and product.get("symbol") == row["symbol"]
                and (product.get("settling_asset") or {}).get("symbol") == row["asset"],
                "conflicting_fill_product")
    return row


def normalize_posting(raw):
    meta = raw.get("meta_data") or {}
    require(isinstance(meta, dict), "invalid_posting_metadata")
    refs = {}
    for key in ("order_id", "fill_id"):
        values = {identifier(source[key]) for source in (raw, meta)
                  if source.get(key) is not None}
        require(len(values) <= 1, "conflicting_posting_reference")
        refs[key] = next(iter(values), None)
    asset, kind = raw.get("asset_symbol"), raw.get("transaction_type")
    require(isinstance(asset, str) and asset and isinstance(kind, str) and kind,
            "invalid_posting_currency_or_type")
    # Delta account-wide postings may have null/zero product IDs.
    pid = raw.get("product_id")
    if pid is not None:
        pid = identifier(pid)
        require(pid.isdigit(), "invalid_posting_product")
        pid = None if int(pid) == 0 else str(int(pid))
    return {"id": identifier(raw.get("id")), "at_us": timestamp_us(raw.get("created_at")),
            "product_id": pid,
            "asset": asset, "type": kind, "amount": decimal_text(raw.get("amount")), **refs}


def unique(rows):
    found = {}
    for row in rows:
        require(row["id"] not in found or found[row["id"]] == row, "conflicting_broker_evidence")
        found[row["id"]] = row
    return sorted(found.values(), key=lambda row: (row["at_us"], row["id"]))


def unavailable(reason):
    return {"financial_reconciliation_status": "awaiting_complete_broker_evidence",
            "reconciliation_version": VERSION, "reconciliation_reason": reason,
            "net_realized_pnl_usd": None, "is_net_realized_pnl": False,
            "funding_reconciled": False}


def analyse(symbol, trade, product, orders, fills, postings, start_us, end_us):
    """Inputs must be freshly fetched complete broker windows, never AI output."""
    pid = identifier(product.get("id"))
    require(product.get("symbol") == symbol and product.get("contract_type") == "perpetual_futures"
            and product.get("notional_type") == "vanilla"
            and (product.get("settling_asset") or {}).get("symbol") == "USD",
            "unsupported_contract_or_currency")
    multiplier = number(product.get("contract_value"))
    precision = product["settling_asset"].get("precision")
    require(multiplier > 0 and type(precision) is int and 0 <= precision <= 18,
            "invalid_contract_specification")
    quantum = Decimal(1).scaleb(-precision)
    entry_id = identifier(trade.get("broker_order_id"))
    exit_ids = {identifier(value) for value in (trade.get("exit_order_ids") or {}).values()}
    require(exit_ids and entry_id not in exit_ids, "missing_or_overlapping_order_ids")
    owned = {entry_id} | exit_ids
    require(set(orders) == owned, "missing_order_evidence")
    side = trade.get("direction")
    require(side in ("LONG", "SHORT"), "invalid_trade_direction")
    entry_side = "buy" if side == "LONG" else "sell"
    signed = 1 if entry_side == "buy" else -1
    for oid, order in orders.items():
        require(str(order.get("id")) == oid and str(order.get("product_id")) == pid
                and (order.get("product_symbol") or order.get("symbol")) == symbol,
                "order_identity_mismatch")
        require(order.get("state") in ("closed", "cancelled"), "orders_not_terminal")
        require(order.get("side") == (entry_side if oid == entry_id else
                ("sell" if entry_side == "buy" else "buy")), "order_side_mismatch")
        if oid == entry_id:
            require(order.get("client_order_id") == trade["id"], "entry_client_id_mismatch")
        requested, unfilled = number(order.get("size")), number(order.get("unfilled_size"))
        require(requested > 0 and 0 <= unfilled <= requested, "invalid_order_quantities")
        if oid == entry_id:
            require(requested == number(trade.get("contracts")), "entry_size_mismatch")
        matched = [f for f in fills if f["order_id"] == oid]
        require(sum((number(f["size"]) for f in matched), ZERO) == requested - unfilled,
                "incomplete_order_fills")
    selected = [f for f in fills if f["order_id"] in owned]
    require(selected, "missing_trade_fills")
    first, last = selected[0]["at_us"], selected[-1]["at_us"]
    require(start_us <= first < last <= end_us - 300 * US, "settlement_window_not_ready")
    require(all(f["product_id"] == pid and f["symbol"] == symbol for f in fills),
            "fill_market_mismatch")
    require(all(f["order_id"] in owned for f in fills if first <= f["at_us"] <= last),
            "overlapping_external_fills")
    balance, cash, fees, quantity = ZERO, ZERO, ZERO, ZERO
    closing = False
    for f in selected:
        require(f["fill_type"] == "normal" and f["asset"] == "USD",
                "unsupported_fill_or_currency")
        require(f["notional_type"] == "vanilla" and number(f["contract_value"]) == multiplier,
                "fill_contract_mismatch")
        size, price = number(f["size"]), number(f["price"])
        is_entry = f["order_id"] == entry_id
        require(f["side"] == (entry_side if is_entry else ("sell" if entry_side == "buy" else "buy")),
                "fill_side_mismatch")
        require(not (is_entry and closing), "interleaved_entry_and_exit")
        closing = closing or not is_entry
        delta = size if f["side"] == "buy" else -size
        balance += delta
        require(balance * signed >= 0, "position_reversal")
        # Broker position after EVERY fill proves an initially flat, isolated
        # lifecycle, catches missing fills and refuses pre-existing exposure.
        require(f["position_after"] is not None and number(f["position_after"]) == balance,
                "position_lifecycle_unverified")
        if is_entry:
            quantity += size
        cash -= delta * price * multiplier
        fees += number(f["commission"])
    require(balance == 0 and quantity > 0, "position_not_fully_closed")
    # A missing broker funding total must ALWAYS prevent final net P&L.
    # First validate the independent cashflow and fee ledger consistency,
    # so those mismatches are not hidden behind a funding-only omission.
    # Neither route can create a report or assume an absent total is zero.
    final_funding = selected[-1]["realized_funding"]
    fill_by_id = {f["id"]: f for f in selected}
    other_orders = {f["order_id"] for f in fills if f["order_id"] not in owned}
    other_fills = {f["id"] for f in fills if f["order_id"] not in owned}
    totals = dict.fromkeys(("cashflow", "commission", "funding"), ZERO)
    attributed = []
    for p in postings:
        if p["type"] in EXTERNAL:
            continue
        oid, fid = p["order_id"], p["fill_id"]
        linked = oid in owned or fid in fill_by_id
        within = first <= p["at_us"] <= last
        same_product = p["product_id"] == pid
        if linked:
            require((oid is None or oid in owned) and (fid is None or fid in fill_by_id)
                    and (oid is None or fid is None or fill_by_id[fid]["order_id"] == oid)
                    and p["product_id"] in (None, pid), "posting_identity_mismatch")
            require(p["at_us"] >= first, "posting_precedes_trade")
        elif same_product and within:
            require(oid is None and fid is None, "overlapping_external_postings")
        elif p["at_us"] >= first and (same_product or p["product_id"] is None):
            if (oid in other_orders or fid in other_fills) and not within:
                continue
            # A currency-only entry could be this trade's fee/tax/adjustment.
            # Unreferenced delayed same-product cashflows are ambiguous too.
            raise ReconciliationError("unattributed_wallet_posting")
        else:
            continue
        require(p["asset"] == "USD", "posting_currency_mismatch")
        require(p["type"] in totals, "unsupported_trade_adjustment")
        # Funding without an explicit reference is attributable only inside
        # the broker-proven isolated position interval. A delayed one leaves
        # the final broker funding total unmatched and therefore unverified.
        totals[p["type"]] += number(p["amount"])
        attributed.append(p)
    def same(a, b):
        return a.quantize(quantum) == b.quantize(quantum)
    require(any(p["type"] == "cashflow" for p in attributed), "missing_cashflow_posting")
    require(any(p["type"] == "commission" for p in attributed), "missing_commission_posting")
    require(same(totals["cashflow"], cash), "wallet_cashflow_mismatch")
    require(same(totals["commission"], -fees), "wallet_commission_mismatch")
    # Hard stop AFTER cashflow+fee validation; never default absent funding
    # to 0 or allow a missing total to become a verified net outcome.
    require(final_funding is not None, "missing_broker_funding_total")
    require(same(totals["funding"], number(final_funding)), "wallet_funding_mismatch")
    net = sum(totals.values(), ZERO)
    entry_value = sum((number(f["price"]) * number(f["size"]) for f in selected
                       if f["order_id"] == entry_id), ZERO)
    exit_value = sum((number(f["price"]) * number(f["size"]) for f in selected
                      if f["order_id"] != entry_id), ZERO)
    return {"financial_reconciliation_status": "broker_reconciled",
            "reconciliation_version": VERSION, "reconciliation_reason": "matched_fills_and_wallet",
            "net_realized_pnl_usd": decimal_text(net), "is_net_realized_pnl": True,
            "funding_reconciled": True, "gross_realized_pnl_usd": decimal_text(totals["cashflow"]),
            "reconciled_fees_usd": decimal_text(-totals["commission"]),
            "funding_cashflow_usd": decimal_text(totals["funding"]),
            # Display averages only; net P&L above uses unrounded fill cashflows.
            "reconciled_entry_price": decimal_text((entry_value / quantity).quantize(Decimal("0.00000001"))),
            "reconciled_exit_price": decimal_text((exit_value / quantity).quantize(Decimal("0.00000001"))),
            "filled_contracts": decimal_text(quantity), "entry_fill_count": sum(f["order_id"] == entry_id for f in selected),
            "exit_fill_count": sum(f["order_id"] != entry_id for f in selected),
            "entry_at_us": first, "exit_at_us": last,
            "reconciliation_as_of_us": end_us,
            "matched_fill_ids": [f["id"] for f in selected],
            "matched_posting_ids": [p["id"] for p in attributed]}


class ReconciliationLedger:
    """Normalized immutable evidence plus append-only reports and ownership."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)

    def record(self, key, fills, postings, report):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS evidence(kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))")
            db.execute("CREATE TABLE IF NOT EXISTS claims(kind TEXT, id TEXT, trade_key TEXT NOT NULL, PRIMARY KEY(kind,id))")
            db.execute("CREATE TABLE IF NOT EXISTS reports(digest TEXT PRIMARY KEY, trade_key TEXT NOT NULL, body TEXT NOT NULL)")
            for table in ("evidence", "claims", "reports"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} "
                               "BEGIN SELECT RAISE(ABORT, 'Immutable reconciliation evidence'); END")
            for kind, rows in (("fill", fills), ("posting", postings)):
                for row in rows:
                    body = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                    old = db.execute("SELECT body FROM evidence WHERE kind=? AND id=?", (kind, row["id"])).fetchone()
                    require(old is None or old[0] == body, "conflicting_broker_evidence")
                    db.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?)", (kind, row["id"], body))
            if report["is_net_realized_pnl"]:
                for kind, ids in (("fill", report["matched_fill_ids"]), ("posting", report["matched_posting_ids"])):
                    for eid in ids:
                        owner = db.execute("SELECT trade_key FROM claims WHERE kind=? AND id=?", (kind, eid)).fetchone()
                        require(owner is None or owner[0] == key, "evidence_already_attributed")
                        db.execute("INSERT OR IGNORE INTO claims VALUES (?,?,?)", (kind, eid, key))
            body = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
            digest = hashlib.sha256((key + "\n" + body).encode()).hexdigest()
            db.execute("INSERT OR IGNORE INTO reports VALUES (?,?,?)", (digest, key, body))


def reconcile_fire(exchange, symbol, trade, ledger_path, *, orders=None, now=None):
    """Review a terminal receipt using signed GETs only; fail closed on any gap."""
    try:
        require(exchange.base_url == DEMO_API and exchange.allow_orders is False, "read_only_demo_required")
        require(symbol in SYMBOLS, "unsupported_market")
        require(trade.get("status") in ("flat_verified", "aborted_flat", "cancelled_flat_verified"),
                "trade_not_confirmed_closed")
        key = symbol + ":" + identifier(trade.get("id"))
        stamp = trade.get("created_at")
        if stamp is None:
            # ChartDesk's local receipt projection uses epoch seconds.
            stamp = datetime.fromtimestamp(trade["at"], timezone.utc).isoformat()
        start = timestamp_us(stamp)
        instant = now or datetime.now(timezone.utc)
        end = timestamp_us(instant.isoformat())
        require(0 < end - start <= 31 * 86400 * US, "history_window_out_of_range")
        product = exchange._request("GET", "/v2/products/" + symbol)["result"]
        pid = product["id"]
        ids = {identifier(trade.get("broker_order_id"))} | {
            identifier(oid) for oid in (trade.get("exit_order_ids") or {}).values()}
        if orders is None:
            orders = {oid: exchange._request("GET", "/v2/orders/" + oid, auth=True)["result"] for oid in sorted(ids)}
        fills = unique([normalize_fill(f) for f in exchange.product_fills(
            pid, start_time_us=start, end_time_us=end)])
        postings = unique([normalize_posting(p) for p in exchange.wallet_postings(start, end)])
        require(all(start <= row["at_us"] <= end for row in fills + postings), "evidence_outside_requested_window")
        try:
            # Plenty of exact arithmetic headroom for the bounded inputs;
            # rounding occurs only at the broker's settlement precision check.
            with localcontext() as context:
                context.prec = 128
                report = analyse(symbol, trade, product, orders, fills, postings, start, end)
        except ReconciliationError as exc:
            report = unavailable(str(exc))
        report.update(reconciliation_as_of_us=end, evidence_window_start_us=start)
        ReconciliationLedger(ledger_path).record(key, fills, postings, report)
        return report
    except ReconciliationError as exc:
        return unavailable(str(exc))
    except Exception:
        # Never return a previous verified result after a failed fresh read,
        # or leak an upstream response body, account details or credentials.
        return unavailable("broker_evidence_or_ledger_unavailable")


def main(argv=None):
    import argparse
    from tradebot.delta import DeltaDemo
    from tradebot.fire_execution import FireTradeStore
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=SYMBOLS, required=True)
    parser.add_argument("--fire-id", required=True)
    parser.add_argument("--data-dir", default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data"))
    args = parser.parse_args(argv)
    root = Path(args.data_dir)
    path = root / ("fire-ops.sqlite" if args.symbol == "BTCUSD" else "fire-xaut.sqlite")
    if not path.is_file():
        parser.error("FIRE receipt database is missing")
    receipt = FireTradeStore(path).receipt(args.fire_id)
    if receipt is None:
        parser.error("FIRE receipt is missing")
    exchange = DeltaDemo(api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
                         api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""), allow_orders=False)
    report = reconcile_fire(exchange, args.symbol, dict(receipt, id=args.fire_id),
                            root / "fire-reconciliation.sqlite")
    print(json.dumps(dict(report, orders_submitted=False, ai_called=False), indent=2))
    if not report["is_net_realized_pnl"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
