"""Explicit one-tap, GPT-6-only BTCUSD Delta India DEMO FIRE execution.

A separate opt-in systemd dashboard setting is required before any POST order.
The broker must confirm the entry fill AND both protective stop orders. The
broker is the authority: acceptance, AI output, or a returned order ID alone
never means a protected trade. No production Delta hostname is supported.

This is NOT a substitute for a continuously running external reconciliation
watchdog and supervised first-order commissioning.
"""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import sqlite3
from threading import Thread
from time import sleep
from uuid import uuid4

from tradebot.delta import DEMO_API, DeltaDemo, DeltaError
from tradebot.execution import DemoExecutor
from tradebot.fire_budget import entry_budget
from tradebot.fire_portfolio_reservation import FirePortfolioReservation
from tradebot.fire_risk import assess_fire_plan
from tradebot.portfolio_equity_guard import PortfolioEquityGuard
from tradebot.fire_indicators import decision_context
from tradebot.fire_entry import FireEntries
from tradebot.fire_market import FireMarket, positions_for_fire
from tradebot.fire_probe import ROLES, decision_failure_code, load_snapshot, run_probe, validate
from tradebot.market import _age_seconds


TERMINAL = frozenset({
    "rejected_no_order", "aborted_flat", "flat_verified",
    "cancelled_flat_verified",
})
# Do not convert unknown exchange states to terminal: they require evidence.
EXPOSED = frozenset({
    "submitting", "reconciling", "verifying_protection",
    "protected_active", "exposure_unknown",
})


class FireTradeError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _dec(raw):
    try:
        d = Decimal(str(raw))
        if not d.is_finite():
            raise ValueError
        return d
    except (TypeError, ValueError, InvalidOperation):
        raise FireTradeError("Invalid broker numeric field") from None


def active_position(exchange, product_id):
    rows = positions_for_fire(exchange)
    if not isinstance(rows, list):
        raise FireTradeError("Invalid broker position list")
    active = []
    for row in rows:
        if not isinstance(row, dict):
            raise FireTradeError("Invalid broker position entry")
        size = _dec(row.get("size"))
        if size != size.to_integral_value():
            raise FireTradeError("Non-integral exchange contract size")
        if size:
            active.append(row)
    if not active:
        return None
    if len(active) != 1 or str(active[0].get("product_id")) != str(product_id):
        raise FireTradeError("Unexpected BTC exposure")
    return active[0]


def _protective_ids(orders, *, product_id, plan):
    """Both distinct child stop orders must be present and active.

    The intended tick-precision SL/TP must appear as broker triggers.
    Price rounding by the broker is NOT silently interpreted as verification.
    """
    if not isinstance(orders, list):
        raise FireTradeError("Invalid open-order list")
    side = "sell" if plan["direction"] == "LONG" else "buy"
    found = {}
    for order in orders:
        if not isinstance(order, dict):
            raise FireTradeError("Malformed broker open-order")
        if str(order.get("product_id")) != str(product_id):
            continue
        category = order.get("stop_order_type")
        if category not in ("stop_loss_order", "take_profit_order"):
            continue
        if (order.get("bracket_order") is not True or
                order.get("side") != side or
                order.get("state") not in ("open", "pending") or
                not order.get("id")):
            continue
        requested = plan["stop_loss"] if category == "stop_loss_order" else plan["take_profit"]
        try:
            matched = _dec(order.get("stop_price")) == _dec(requested)
        except FireTradeError:
            matched = False
        if matched:
            found.setdefault(category, set()).add(str(order["id"]))
    return found


def protective_orders_verified(orders, *, product_id, plan):
    found = _protective_ids(orders, product_id=product_id, plan=plan)
    return bool(found.get("stop_loss_order") and found.get("take_profit_order")
                and found["stop_loss_order"].isdisjoint(found["take_profit_order"]))



class FireTradeStore:
    """Durable cross-process manual-press reservation; no automatic reposting."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise FireTradeError("FIRE database cannot be a symlink")
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fire_requests(
                press TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT NOT NULL)""")
            db.commit()

    def record_model_input(self, press, snapshot):
        # Keep exact FIRE inputs in the private operations DB, outside the
        # public browser projection which only exposes the decision quote.
        with closing(self._connect()) as db:
            db.execute("CREATE TABLE IF NOT EXISTS fire_model_inputs "
                       "(press TEXT PRIMARY KEY, snapshot TEXT NOT NULL)")
            db.execute("INSERT INTO fire_model_inputs VALUES (?,?)",
                       (press, json.dumps(snapshot, allow_nan=False, separators=(",", ":"))))
            db.commit()

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def latest(self):
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT press,created_at,updated_at,status,result "
                "FROM fire_requests ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"status": "idle"}
        return dict(press=row[0], created_at=row[1], updated_at=row[2],
                    status=row[3], **json.loads(row[4]))

    def last_closed_position(self):
        with closing(self._connect()) as db:
            row = db.execute("SELECT result FROM fire_requests WHERE status='flat_verified' "
                             "ORDER BY created_at DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def receipt(self, press):
        with closing(self._connect()) as db:
            row = db.execute("SELECT created_at,updated_at,status,result FROM fire_requests WHERE press=?",
                             (press,)).fetchone()
        if row:
            return dict(press=press, created_at=row[0], updated_at=row[1], status=row[2], **json.loads(row[3]))

    def reserve(self, *, when=None, press=None):
        when = when or _now()
        if when.tzinfo is None:
            raise FireTradeError("Timezone-aware clock required")
        press = press or uuid4().hex
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM fire_requests WHERE press=?", (press,)).fetchone():
                return None
            old = db.execute(
                "SELECT status,created_at FROM fire_requests "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if old:
                if old[0] not in TERMINAL:
                    raise FireTradeError("Previous FIRE needs broker reconciliation")
                age = (when - datetime.fromisoformat(old[1])).total_seconds()
                if old[0] != "flat_verified" and age < 300:
                    raise FireTradeError("FIRE cooldown active")
            stamp = when.isoformat()
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (press, stamp, stamp, "requested", "{}"))
            db.commit()
        return press

    def update(self, press, status, **fields):
        if status not in (TERMINAL | EXPOSED |
                          {"requested", "reasoning", "preflight"}):
            raise FireTradeError("Unsupported FIRE state")
        # Only audited fields; never accept provider response bodies or keys.
        allowed = {"model", "direction", "contracts", "stop_loss",
                   "take_profit", "broker_order_id", "order_state",
                   "protection_verified", "orders_submitted",
                   "model_latency_ms", "budget", "sizing_estimate", "risk_assessment", "reason_code", "snapshot_at", "thesis", "decision_at", "entry", "exit_order_ids", "protected_at", "decision_quote", "indicators"}
        if set(fields) - allowed:
            raise FireTradeError("Unexpected FIRE status data")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,result FROM fire_requests WHERE press=?", (press,)
            ).fetchone()
            if row is None:
                raise FireTradeError("FIRE receipt missing")
            if row[0] in TERMINAL and status != row[0]:
                raise FireTradeError("Terminal verified FIRE cannot be reopened")
            current = json.loads(row[1])
            current.update(fields)
            db.execute(
                "UPDATE fire_requests SET status=?,updated_at=?,result=? WHERE press=?",
                (status, _now().isoformat(),
                 json.dumps(current, separators=(",", ":"), allow_nan=False), press)
            )
            db.commit()
            return {"press": press, "status": status, **current}


def _live_preflight(exchange, snapshot, plan):
    if getattr(exchange, "base_url", None) != DEMO_API or not exchange.allow_orders:
        raise FireTradeError("Demo-only trading API required")
    symbol = snapshot["core"]["ticker"]["symbol"]
    ticker = exchange.ticker(symbol)
    if not isinstance(ticker, dict) or (ticker.get("symbol"), ticker.get("product_id")) != (symbol, snapshot["core"]["ticker"]["product_id"]):
        raise FireTradeError("Selected market ticker mismatch")
    if _age_seconds(ticker.get("timestamp"), _now()) > 30:
        raise FireTradeError("Stale broker quote")
    q = ticker.get("quotes") or {}
    bid, ask = _dec(q.get("best_bid")), _dec(q.get("best_ask"))
    if bid <= 0 or ask <= bid:
        raise FireTradeError("Invalid broker spread")
    validate(plan, {"best_bid": str(bid), "best_ask": str(ask)})
    mark = _dec(ticker.get("mark_price"))
    stop, target = _dec(plan["stop_loss"]), _dec(plan["take_profit"])
    if (mark <= 0 or not (
            stop < mark < target if plan["direction"] == "LONG"
            else target < mark < stop)):
        raise FireTradeError("Protective orders already crossed the broker mark price")
    earlier = (_dec(snapshot["core"]["best_bid"]) +
               _dec(snapshot["core"]["best_ask"])) / 2
    current = (bid + ask) / 2
    if abs(current / earlier - 1) > Decimal("0.005"):
        raise FireTradeError("Market moved after GPT-6 analysis")
    if exchange.open_orders():
        raise FireTradeError("Existing exchange orders require reconciliation")
    if active_position(exchange, snapshot["core"]["ticker"]["product_id"]):
        raise FireTradeError("An existing position must be closed first")
    return {"mark": mark, "best_bid": bid, "best_ask": ask}


def _protection_check(exchange, receipt, *, pause=sleep, attempts=6):
    plan = receipt["plan"]
    product_id = receipt["product_id"]
    direction = 1 if plan["direction"] == "LONG" else -1
    for attempt in range(attempts):
        position = active_position(exchange, product_id)
        orders = exchange.open_orders()
        if position is None and not orders:
            # Parent has filled and exchange reports no further exposure.
            # This is verified flat, not evidence that SL or TP caused exit.
            return "flat_verified"
        if position is not None:
            size = _dec(position["size"])
            if int(size) != direction * plan["contracts"]:
                raise FireTradeError("Exchange position does not match entry fill")
            if protective_orders_verified(orders, product_id=product_id, plan=plan):
                found = _protective_ids(orders, product_id=product_id, plan=plan)
                receipt["exit_order_ids"] = {kind: next(iter(ids)) for kind, ids in found.items()
                                             if len(ids) == 1}
                receipt["protected_at"] = _now().isoformat()
                return "protected_active"
        if attempt < attempts - 1:
            pause(1)
    raise FireTradeError("Both protective orders not verified")


class FireDemoController:
    """Background worker only when manually activated via authenticated UI."""

    def __init__(self, path, *, enabled=False, exchange_factory=None,
                 snapshot_loader=load_snapshot, probe=run_probe,
                 pause=sleep, spawn=None, symbol="BTCUSD"):
        self.symbol = symbol
        self.enabled = bool(enabled)
        self.store = FireTradeStore(path)
        self.path = Path(path)
        self.portfolio_reservation = FirePortfolioReservation(self.path.parent)
        self.equity_guard = PortfolioEquityGuard(self.path.parent / "fire-equity-risk.sqlite")
        self.exchange_factory = exchange_factory or (lambda: FireMarket(self.symbol,
            api_key=os.environ["DELTA_DEMO_API_KEY"],
            api_secret=os.environ["DELTA_DEMO_API_SECRET"],
            allow_orders=True,
        ))
        self.archive = None
        self.snapshot_loader = snapshot_loader
        self.probe = probe
        self.pause = pause
        self.spawn = spawn or (lambda f: Thread(target=f, daemon=True).start())

    def snapshot(self):
        result = self.store.latest()
        return {**result, "symbol": self.symbol,
                "mode": "delta_india_demo_execution" if self.enabled else "disabled",
                "execution_enabled": self.enabled, "model": "tb-gpt-6",
                "account": "Delta India Demo only",
                "market_margin_percent": 20,
                "protection_verified": result.get("protection_verified") is True,
                "orders_submitted": result.get("orders_submitted") is True}

    def start(self, *, press=None):
        if not self.enabled:
            return False, "execution_disabled"
        try:
            press = self.store.reserve(press=press)
        except FireTradeError:
            return False, "existing_trade_or_cooldown"
        if press is None:
            return True, "existing_receipt"
        self.spawn(lambda: self._run(press))
        return True, "accepted"

    def _run(self, press):
        stage = "market_snapshot"
        submitted = False
        exchange = None
        try:
            self.store.update(press, "reasoning", model="tb-gpt-6",
                              orders_submitted=False, protection_verified=False)
            stage = "portfolio_entry_reservation"
            if not self.portfolio_reservation.claim(self.symbol, press, self.path):
                raise FireTradeError("Another unresolved FIRE reserves this account")
            # One fresh snapshot is used by both GPT-6 and this execution.
            snapshot = self.snapshot_loader() if self.symbol == "BTCUSD" else self.snapshot_loader(self.symbol)
            if snapshot["core"]["ticker"]["symbol"] != self.symbol:
                raise FireTradeError("Snapshot market mismatch")
            collected = datetime.fromisoformat(snapshot["collected_at"])
            if (collected.tzinfo is None or
                    (_now() - collected).total_seconds() > 60):
                raise FireTradeError("Stale market snapshot")
            exchange = self.exchange_factory()
            product_id = snapshot["core"]["ticker"]["product_id"]
            stage = "market_availability"
            if snapshot["position_contracts"] or active_position(exchange, product_id) or exchange.open_orders():
                raise FireTradeError("Selected market already has a position or pending order")
            stage = "margin_budget"
            price = max(_dec(snapshot["core"]["best_ask"]), _dec(snapshot["core"]["ticker"]["mark_price"]))
            budget = entry_budget(exchange, self.symbol, product_id, price)
            self.store.update(press, "reasoning", budget=budget)
            if budget["max_contracts_per_entry"] < 1:
                raise FireTradeError("Insufficient margin budget for one contract")
            stage = "portfolio_equity_limits"
            if getattr(exchange, "base_url", None) != DEMO_API:
                raise FireTradeError("Only signed Delta Demo equity accepted")
            equity_precheck = self.equity_guard.require_approved(budget["equity_usd"])
            self.store.update(press, "reasoning", risk_assessment={
                "equity_monitor": equity_precheck})
            midpoint = (float(snapshot["core"]["best_bid"]) + float(snapshot["core"]["best_ask"])) / 2
            context = decision_context(exchange, self.store, self.symbol, collected.timestamp(), midpoint)
            if self.archive is not None:
                stage = "historical_data_integrity"
                try:
                    levels = self.archive.levels(self.symbol, collected.timestamp(), midpoint)
                except (sqlite3.Error, ValueError, TypeError):
                    raise FireTradeError("Historical levels unavailable") from None
                periods = levels.get("periods") if isinstance(levels, dict) else None
                required = ("day", "previous_day", "week", "previous_week",
                            "month", "previous_month")
                if not isinstance(periods, dict) or any(
                    not isinstance(periods.get(key), dict)
                    or periods[key].get("quality_status") != "provisionally_valid"
                    for key in required
                ):
                    raise FireTradeError("Unverified historical levels; no FIRE order")
                context["historical_levels"] = levels
            self.store.update(press, "reasoning", indicators=context)
            model_snapshot = {**snapshot, "indicators": context, "fire_execution_scope": {
                "environment": "delta-india-demo",
                "instrument": self.symbol + " perpetual futures",
                **budget,
                "attached_stop_loss_and_take_profit_required": True,
                "separate_learning_model_has_no_trade_authority": True,
            }}
            stage = "save_model_input"
            self.store.record_model_input(press, model_snapshot)
            stage = "model_request"
            report = self.probe(dict(ROLES), lambda: model_snapshot)
            raw = (report.get("results") or {}).get("fire") or {}
            stage = "model_decision"
            if "decision" not in raw:
                self.store.update(press, "rejected_no_order", model_latency_ms=raw.get("latency_ms"),
                                  reason_code=decision_failure_code(raw.get("error")),
                                  orders_submitted=False, protection_verified=False)
                return
            plan = validate(raw["decision"], snapshot["core"])
            if plan["direction"] == "WAIT":
                self.store.update(
                    press, "rejected_no_order", model_latency_ms=raw.get("latency_ms"),
                    reason_code="gpt6_wait_no_trade",
                    thesis=str(raw.get("thesis") or raw["decision"].get("thesis") or "")[:350],
                    orders_submitted=False, protection_verified=False)
                return
            self.store.update(
                press, "preflight", direction=plan["direction"], model_latency_ms=raw.get("latency_ms"),
                contracts=plan["contracts"], stop_loss=plan["stop_loss"],
                take_profit=plan["take_profit"],
                snapshot_at=snapshot["collected_at"], decision_at=_now().isoformat(),
                decision_quote={k: snapshot["core"].get(k) for k in ("best_bid","best_ask")},
                thesis=str(raw.get("thesis") or "")[:350])
            stage = "contract_size"
            if not 1 <= plan["contracts"] <= budget["max_contracts_per_entry"]:
                raise FireTradeError("Order exceeds market budget")
            stage = "exchange_preflight"
            exchange_quote = _live_preflight(exchange, snapshot, plan)
            price = max(exchange_quote["mark"], exchange_quote["best_ask"])
            stage = "margin_budget_recheck"
            current_budget = entry_budget(exchange, self.symbol, product_id, price)
            self.store.update(press, "preflight", budget=current_budget)
            if plan["contracts"] > current_budget["max_contracts_per_entry"]:
                raise FireTradeError("Live margin budget changed")
            stage = "portfolio_equity_limits_recheck"
            equity_recheck = self.equity_guard.require_approved(current_budget["equity_usd"])
            stage = "risk_governor"
            risk_assessment = assess_fire_plan(plan, current_budget, exchange_quote)
            self.store.update(press, "preflight", risk_assessment={
                **risk_assessment, "equity_monitor": equity_recheck})
            units = _dec(current_budget["contract_value"]) * plan["contracts"]
            estimated_entry = exchange_quote["best_ask" if plan["direction"] == "LONG" else "best_bid"]
            self.store.update(press, "submitting", sizing_estimate={
                "notional_usd": str(units * estimated_entry),
                "loss_at_stop_usd": str(units * abs(estimated_entry - _dec(plan["stop_loss"]))),
            })
            submitted = True  # Exchange outcome could become uncertain after call.
            entries = FireEntries(self.path, exchange)
            receipt = entries.submit_first_entry(press, snapshot, plan)
            for attempt in range(5):
                if receipt["status"] == "filled":
                    break
                if receipt["status"] in ("cancelled",):
                    break
                self.store.update(press, "reconciling")
                if attempt:
                    self.pause(1)
                receipt = entries.reconcile(press)
            if receipt["status"] != "filled":
                raise FireTradeError("No fully reconciled entry fill")
            # The signed broker lookup is authoritative, not the HTTP
            # acceptance payload or a locally inferred market fill.
            broker_order = exchange.order_by_client_id(press)
            if (not isinstance(broker_order, dict) or
                    broker_order.get("client_order_id") != press or
                    str(broker_order.get("product_id")) != str(receipt["product_id"]) or
                    broker_order.get("id") != receipt.get("order_id") or
                    broker_order.get("state") != "closed" or
                    str(broker_order.get("unfilled_size")) != "0"):
                raise FireTradeError("Entry fill not confirmed by signed order lookup")
            self.store.update(
                press, "verifying_protection", broker_order_id=str(
                    receipt.get("order_id") or "")[:64], order_state="filled", entry={"price": broker_order.get("average_fill_price"),
                                                "at": broker_order.get("updated_at")},
                orders_submitted=True)
            state = _protection_check(exchange, receipt, pause=self.pause)
            self.store.update(
                press, state, protection_verified=state == "protected_active",
                exit_order_ids=receipt.get("exit_order_ids", {}), protected_at=receipt.get("protected_at"),
                orders_submitted=True)
        except Exception:
            # No raw provider/broker error is logged or returned to browser.
            if not submitted:
                self.store.update(press, "rejected_no_order",
                                  reason_code=stage + "_failed",
                                  protection_verified=False,
                                  orders_submitted=False)
                return
            # FireEntries always commits a durable intent before making
            # a broker POST. If no such row exists, no order was submitted
            # by FIRE: do NOT cancel an unrelated manual order that appeared
            # between our preflight and submission.
            try:
                with closing(sqlite3.connect(self.path, timeout=10)) as db:
                    has_table = db.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type='table' AND name='fire_entries'"
                    ).fetchone()
                    intent = db.execute(
                        "SELECT 1 FROM fire_entries WHERE press=?", (press,)
                    ).fetchone() if has_table else None
                if intent is None:
                    self.store.update(press, "rejected_no_order",
                                      reason_code="no_durable_broker_intent",
                                      protection_verified=False,
                                      orders_submitted=False)
                    return
            except sqlite3.Error:
                # DB uncertainty means we cannot prove the absence of a POST.
                pass
            # An ambiguous POST result might still have filled.
            # Close out BTC exposure; never repost the original FIRE request.
            self.store.update(press, "exposure_unknown",
                              reason_code="execution_or_protection_unverified",
                              orders_submitted=True, protection_verified=False)
            try:
                exchange = exchange or self.exchange_factory()
                if isinstance(exchange, FireMarket):
                    exchange.close_exposure(self.pause)
                else:
                    DemoExecutor(exchange, schedule="crypto-24x7", pause=self.pause,
                                 journal_path=str(self.path.parent / "trades.jsonl")).closeout(max_attempts=3)
                self.store.update(
                    press, "flat_verified", orders_submitted=True,
                    protection_verified=False, reason_code="emergency_flat_verified")
            except Exception:
                # Only separate broker reconciliation can resolve this halt.
                pass
