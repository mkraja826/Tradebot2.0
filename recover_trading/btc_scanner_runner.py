"""Original BTC scanner with deterministic execution on the designated demo wallet."""
import hashlib
import time
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR

from .btc_scanner_runner_rules import entry_plan, trailing_stop
from .entry_quotes import quote_evidence


def gold_volatility_stop(db, cid, side, fill, current, frame, tick):
    """Trail observed post-fill five-minute extremes, using three ATR14."""
    fill, current, tick = (D(str(value)) for value in (fill, current, tick))
    atr = D(str(frame["features"]["atr14"]))
    long = side == "buy"
    bar_extreme = D(str(frame["candle"]["high" if long else "low"]))
    if side not in ("buy", "sell") or any(
        not value.is_finite() or value <= 0 for value in (fill, current, tick, atr, bar_extreme)
    ):
        raise ValueError("invalid Gold trail input")
    closed = int(frame["closed_at"])
    with db:
        db.execute("""CREATE TABLE IF NOT EXISTS gold_trail_state (
            client_id TEXT PRIMARY KEY, observed_at INTEGER NOT NULL,
            last_close INTEGER NOT NULL, extreme TEXT NOT NULL)""")
        # A receipt can arrive after its fill. Ignore any candle that may
        # contain prices from before we first confirmed the filled position.
        db.execute("INSERT OR IGNORE INTO gold_trail_state VALUES (?, ?, 0, ?)",
                   (cid, time.time_ns() // 1_000_000_000 + 1, str(fill)))
        observed, last, saved = db.execute(
            "SELECT observed_at, last_close, extreme FROM gold_trail_state WHERE client_id=?",
            (cid,)).fetchone()
        if closed - 300 < observed or closed < last:
            return current
        extreme = max(D(saved), bar_extreme) if long else min(D(saved), bar_extreme)
        db.execute("UPDATE gold_trail_state SET last_close=?, extreme=? WHERE client_id=?",
                   (closed, str(extreme), cid))
    raw = extreme - 3 * atr if long else extreme + 3 * atr
    rounding = ROUND_FLOOR if long else ROUND_CEILING
    candidate = (raw / tick).to_integral_value(rounding=rounding) * tick
    return max(current, candidate) if long else min(current, candidate)


def cycle(broker, db, report, *, gold_id=None):
    symbol = "BTCUSD" if gold_id is None else "XAUTUSD"
    account_id = "26679287" if gold_id is None else str(gold_id)
    if gold_id is not None and (not account_id.isdigit() or int(account_id) <= 0 or int(account_id) == 26679287):
        raise ValueError("Invalid Gold account")
    table = "btc_runner_entries" if gold_id is None else "gold_runner_entries"
    db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
        client_id TEXT PRIMARY KEY, side TEXT, stop TEXT, created INTEGER,
        state TEXT)""")
    if report.get("symbol") != symbol or report.get("status") == "scan_error":
        return "scan_unavailable"
    frame = report["market_context"]["frames"]["5m"]
    closed = int(frame["closed_at"])
    if not 0 <= time.time() - closed < 330:
        return "awaiting_fresh_bar"
    features = frame["features"]
    wallet, = [w for w in broker.wallet()["result"] if w.get("asset_symbol") == "USD"]
    if str(wallet.get("user_id")) != account_id:
        return "btc_wallet_mismatch" if gold_id is None else "gold_wallet_mismatch"
    product = broker.product(symbol)
    if (product["symbol"] != symbol or product["contract_unit_currency"] != ("BTC" if gold_id is None else "XAUT")
            or product["settling_asset"]["symbol"] != "USD" or product["notional_type"] != "vanilla"):
        return "unsupported_contract"
    pid = product["id"]
    positions = broker.positions(pid)
    if isinstance(positions, dict):
        positions = [positions]
    positions = [p for p in positions if D(str(p["size"])) != 0]
    page = broker.active_orders_page(pid)
    if page.get("meta", {}).get("after"):
        return "order_snapshot_incomplete"
    orders = page["result"]
    latest = db.execute(f"SELECT client_id,side,stop,created,state FROM {table} WHERE state!='done' ORDER BY created DESC LIMIT 1").fetchone()
    if latest:
        cid, side, initial, created, state = latest
        receipt = broker.order(cid)
        if receipt.get("client_order_id") != cid or receipt.get("product_id") != pid:
            return "entry_receipt_unverified"
        if receipt.get("state") not in ("closed", "cancelled"):
            return "entry_pending"
        if not positions and not orders:
            if time.time()-created < 60:
                return "awaiting_position_sync"
            with db:
                db.execute(f"UPDATE {table} SET state='done' WHERE client_id=?", (cid,))
            return "flat_reconciled"
        if len(positions) != 1 or len(orders) != 1:
            return "inspect_position_protection"
        pos, leg = positions[0], orders[0]
        qty = D(str(pos["size"]))
        filled = D(str(receipt["size"])) - D(str(receipt["unfilled_size"]))
        if (receipt["side"] != side or abs(qty) != filled or (qty > 0) != (side == "buy")
                or D(str(pos["entry_price"])) != D(str(receipt["average_fill_price"]))
                or leg.get("product_id") != pid or leg.get("side") != ("sell" if side == "buy" else "buy")
                or leg.get("stop_order_type") != "stop_loss_order"
                or leg.get("stop_trigger_method") != "mark_price"
                or D(str(leg["size"])) != abs(qty)):
            return "position_or_stop_unverified"
        current = D(str(leg["stop_price"]))
        if gold_id is not None:
            candidate = gold_volatility_stop(db, cid, side, pos["entry_price"], current,
                                             frame, product["tick_size"])
        else:
            candidate = trailing_stop(side, pos["entry_price"], initial, current,
                                      frame["candle"]["close"], features["ema9"], features["atr14"], product["tick_size"])
        if candidate == current:
            return "holding"
        ticker = broker.ticker(symbol)
        mark = D(str(ticker["mark_price"]))
        if (ticker.get("product_id") != pid or not 0 <= time.time_ns()//1000-int(ticker["timestamp"]) <= 30000000
                or (candidate >= mark if side == "buy" else candidate <= mark)):
            return "stop_update_unavailable"
        broker._request("PUT", "/v2/orders", auth=True, payload={
            "id": leg["id"], "product_id": pid, "size": int(abs(qty)), "stop_price": str(candidate)})
        return "trail_submitted"
    if positions or orders:
        return "existing_exposure"
    direction = report["direction_engine"]["direction"]
    if direction == "NEUTRAL" or not report.get("signals"):
        return "no_signal"
    ticker = broker.ticker(symbol)
    quote = quote_evidence(ticker, symbol, pid, time.time_ns()//1000)
    if quote.get("status") != "fresh_book":
        return "quote_unavailable"
    plan = entry_plan(direction, wallet["balance"], quote["best_bid"], quote["best_ask"],
                      product["contract_value"], product["tick_size"], features["atr14"])
    if not plan:
        return "below_one_contract"
    prefix = "btc-runner" if gold_id is None else "gold-runner"
    cid = hashlib.sha256(f"{prefix}:{closed}".encode()).hexdigest()[:32]
    with db:
        inserted = db.execute(f"INSERT OR IGNORE INTO {table}(client_id,side,stop,created,state) VALUES(?,?,?,?,?)",
                              (cid,plan["side"],str(plan["stop_loss"]),int(time.time()),"reserved")).rowcount
    if not inserted:
        return "bar_already_evaluated"
    try:
        leverage = broker.set_order_leverage(pid)
        if D(str(leverage["leverage"])) != 20:
            raise ValueError("unexpected leverage")
    except Exception:
        with db:
            db.execute(f"UPDATE {table} SET state='done' WHERE client_id=?", (cid,))
        raise
    broker._request("POST", "/v2/orders", auth=True, payload={
        "product_id":pid, "client_order_id":cid, "order_type":"market_order",
        "size":plan["size"], "side":plan["side"], "bracket_stop_trigger_method":"mark_price",
        "bracket_stop_loss_price":str(plan["stop_loss"])})
    return "entry_submitted"
