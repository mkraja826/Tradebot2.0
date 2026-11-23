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
from tradebot.fire_leverage import synchronize_leverage, verify_liquidation_clearance, LeverageRejected, LiquidationUnsafe
from tradebot.fire_account_guard import require_flat_demo_account
from tradebot.fire_portfolio_reservation import FirePortfolioReservation
from tradebot.fire_risk import assess_fire_plan, FireRiskLimits, RiskRejected
from tradebot.portfolio_equity_guard import RuntimeEquityGuard
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


# Report only fixed, source-controlled risk labels, never raw exceptions.
RISK_REJECTION_LABELS = {
    "Invalid proposal size or direction": "invalid_side_or_quantity",
    "Proposed size exceeds scoped BTC DEMO quantity policy": "quantity_cap_exceeded",
    "Above verified margin limit": "margin_capacity_exceeded",
    "GPT-6 proposed leverage outside 1..20": "leverage_outside_policy",
    "Margin budget not calculated for proposed leverage": "leverage_budget_mismatch",
    "Missing or invalid verified risk input": "risk_input_invalid",
    "Unexpected broker fee rate": "broker_fee_unverified",
    "Invalid stop or target against executable quote": "stop_target_quote_invalid",
    "Stop distance exceeds allowed reward distance": "stop_distance_exceeds_target",
    "Non-positive net reward or invalid risk": "net_reward_nonpositive",
    "Stop-loss exposure exceeds equity risk limit": "equity_risk_ceiling_exceeded",
    "Effective leverage exceeds policy": "effective_leverage_exceeded",
    "Stop too close to theoretical liquidation at selected leverage": "liquidation_cushion_insufficient",
    "Expected net reward-to-risk below policy": "net_reward_risk_below_policy",
}


def safe_risk_rejection_detail(exc):
    if not isinstance(exc, RiskRejected):
        return "unexpected_risk_exception"
    return RISK_REJECTION_LABELS.get(str(exc), "unclassified_risk_rejection")


def _pretrade_quote_distance_evidence(model_core, checked_quote, plan):
    """Explain 1:1 reject across model versus signed pre-order broker quote.

    Pure audit evidence: never modifies orders, stops, targets or admission.
    """
    try:
        side = plan["direction"]
        if side not in ("LONG", "SHORT"):
            return {}
        key = "best_ask" if side == "LONG" else "best_bid"
        model_entry = _dec(model_core[key])
        broker_entry = _dec(checked_quote[key])
        stop = _dec(plan["stop_loss"])
        target = _dec(plan["take_profit"])
        if model_entry <= 0 or broker_entry <= 0:
            return {}
        def geometry(entry):
            risk = entry-stop if side == "LONG" else stop-entry
            reward = target-entry if side == "LONG" else entry-target
            return {"stop_distance": str(risk), "target_distance": str(reward),
                    "gross_reward_risk": str(reward/risk) if risk > 0 else None,
                    "gross_1_to_1_satisfied": risk > 0 and reward >= risk}
        return {"source": "snapshot_vs_signed_broker_quote",
                "model_entry": str(model_entry),
                "broker_entry": str(broker_entry),
                "quote_change_bps": str(
                    (broker_entry/model_entry-Decimal("1"))*Decimal("10000")),
                "model": geometry(model_entry),
                "broker": geometry(broker_entry)}
    except (ValueError, TypeError, KeyError, FireTradeError):
        return {}


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
    expected_size = plan["contracts"]
    if type(expected_size) is not int or expected_size < 1:
        raise FireTradeError("Invalid protective contract size")
    found = {}
    for order in orders:
        if not isinstance(order, dict):
            raise FireTradeError("Malformed broker open-order")
        if str(order.get("product_id")) != str(product_id):
            continue
        category = order.get("stop_order_type")
        if category not in ("stop_loss_order", "take_profit_order"):
            # A third same-product order (including a manual/unknown order)
            # invalidates exclusive bracket protection. The chosen FIRE
            # cannot safely attribute that order to its parent fill.
            return {}
        order_id = order.get("id")
        id_valid = ((type(order_id) is int and order_id > 0)
                    or (type(order_id) is str and bool(order_id.strip())))
        if (order.get("bracket_order") is not True or
                order.get("side") != side or
                order.get("state") not in ("open", "pending") or
                not id_valid):
            # An invalid same-product protective child cannot be ignored
            # simply because one valid SL and TP pair also exists.
            return {}
        requested = plan["stop_loss"] if category == "stop_loss_order" else plan["take_profit"]
        try:
            size = _dec(order.get("size"))
            matched = (size == expected_size and
                       _dec(order.get("stop_price")) == _dec(requested))
        except FireTradeError:
            matched = False
        if not matched:
            # Any other open bracket for this exact product can prematurely
            # close or over-close the position even if our expected pair is
            # otherwise present. Fail closed instead of filtering it away.
            return {}
        # Two matching child orders are not interchangeable redundancy:
        # either could close/over-close the same net position. With more
        # than one matching order, verification is ambiguous and must
        # trigger the existing emergency-protection path.
        found.setdefault(category, []).append(str(order_id))
    return found


def protective_orders_verified(orders, *, product_id, plan):
    found = _protective_ids(orders, product_id=product_id, plan=plan)
    return bool(len(found.get("stop_loss_order", ())) == 1 and
                len(found.get("take_profit_order", ())) == 1 and
                found["stop_loss_order"][0] != found["take_profit_order"][0])



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
            # The newest receipt being terminal does not prove older FIRE
            # requests are resolved. Check every durable status under the
            # same write lock: older protected/unknown/unknown-status rows
            # must never be hidden by a newer rejected or flat receipt.
            terminal = tuple(sorted(TERMINAL))
            placeholders = ",".join("?" for _ in terminal)
            outstanding = db.execute(
                "SELECT 1 FROM fire_requests WHERE status NOT IN ("
                + placeholders + ") LIMIT 1", terminal
            ).fetchone()
            if outstanding:
                raise FireTradeError("Previous FIRE needs broker reconciliation")
            old = db.execute(
                "SELECT status,created_at FROM fire_requests "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1"
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
                   "model_latency_ms", "budget", "sizing_estimate", "sizing_evidence", "risk_assessment", "reason_code", "risk_rejection_detail", "risk_quote_diagnostics", "snapshot_at", "thesis", "decision_at", "entry", "exit_order_ids", "protected_at", "decision_quote", "indicators", "selected_leverage", "liquidation_verified", "liquidation_price"}
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
    # Delta can normalize off-tick bracket trigger prices. Because protection
    # verification requires the exact requested triggers, reject off-grid
    # prices BEFORE the order instead of relying on post-fill emergency exit.
    product = exchange._request("GET", "/v2/products/" + symbol)["result"]
    if (not isinstance(product, dict) or
            str(product.get("id")) != str(snapshot["core"]["ticker"]["product_id"]) or
            product.get("symbol") != symbol):
        raise FireTradeError("Selected broker product not verified")
    tick = _dec(product.get("tick_size"))
    if tick <= 0:
        raise FireTradeError("Invalid broker tick size")
    for price_name in ("stop_loss", "take_profit"):
        requested = _dec(plan[price_name])
        if requested <= 0 or requested % tick != 0:
            raise FireTradeError("GPT-6 exit price not aligned to current broker tick size")
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


def _protection_check(exchange, receipt, *, pause=sleep, attempts=12):
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
                receipt["exit_order_ids"] = {kind: ids[0] for kind, ids in found.items()
                                             if len(ids) == 1}
                receipt["protected_at"] = _now().isoformat()
                try:
                    receipt.update(verify_liquidation_clearance(exchange, product_id, plan, position))
                except LiquidationUnsafe:
                    # Broker evidence explicitly places liquidation inside
                    # the stop buffer. Any retry delays emergency closeout.
                    raise
                except LeverageRejected:
                    # Only missing/stale margin evidence is temporarily
                    # retried; after the bounded window, fail closed.
                    if attempt == attempts - 1:
                        raise
                    pause(1)
                    continue
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
        self.equity_guard = RuntimeEquityGuard(self.path.parent / "fire-equity-risk.sqlite")
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

    def _decision_model_id(self):
        """Default BTC/manual FIRE remains GPT-6; only Gold overrides."""
        return "tb-gpt-6"

    def _decision_context(self, exchange, collected, midpoint):
        """Normal FIRE uses its existing independent provider context."""
        return decision_context(exchange, self.store, self.symbol,
                                collected.timestamp(), midpoint)

    def _historical_levels(self, collected, midpoint):
        """Preserve all six normal FIRE periods and strict quality gates."""
        if self.archive is None:
            raise FireTradeError("Historical candle archive not configured")
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
        return levels

    def _additional_fire_scope(self):
        """Normal six-period policy never claims supervised pilot history."""
        return {}

    def _max_contracts_for_entry(self, budget):
        """Normal FIRE retains the broker's existing checked risk limit."""
        return budget["max_contracts_per_entry"]

    def _hard_contract_cap(self):
        """All legacy FIRE paths retain the independent one-contract cap."""
        return 1

    def _entry_budget(self, exchange, product_id, price, *, planned_leverage=None):
        return entry_budget(exchange, self.symbol, product_id, price,
                            planned_leverage=planned_leverage,
                            max_contracts_limit=self._hard_contract_cap())

    def _model_entry_budget(self, exchange, product_id, price):
        """Default FIRE exposes current broker leverage, not a hypothetical."""
        return self._entry_budget(exchange, product_id, price)

    def _assess_risk(self, plan, budget, quote):
        return assess_fire_plan(plan, budget, quote,
                                limits=FireRiskLimits(max_contracts=self._hard_contract_cap()))

    def _normalize_plan(self, plan, context):
        """Default FIRE never adjusts an independently validated model plan."""
        return plan

    def _allow_wait_choice(self):
        """Manual/supervised modes retain the legitimate no-entry model action."""
        return True

    def _entry_sizing_record(self):
        """Normal/supervised FIRE receipts have no experimental sizing tier."""
        return {}

    def _require_account_flat(self, exchange, product_id):
        """Normal FIRE keeps signed isolated-margin and full exposure proofs."""
        return require_flat_demo_account(
            exchange, selected_symbol=self.symbol, selected_product_id=product_id)

    def _pre_model_market_screen(self, snapshot, context):
        """Normal FIRE is unchanged; optional strategy screen cannot authorize."""
        return None

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
            self.store.update(press, "reasoning", model=self._decision_model_id(),
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
            stage = "account_exposure_preflight"
            self._require_account_flat(exchange, product_id)
            stage = "margin_budget"
            price = max(_dec(snapshot["core"]["best_ask"]), _dec(snapshot["core"]["ticker"]["mark_price"]))
            budget = self._model_entry_budget(exchange, product_id, price)
            self.store.update(press, "reasoning", budget=budget)
            if budget["max_contracts_per_entry"] < 1:
                raise FireTradeError("Insufficient margin budget for one contract")
            stage = "portfolio_equity_limits"
            if getattr(exchange, "base_url", None) != DEMO_API:
                raise FireTradeError("Only signed Delta Demo equity accepted")
            equity_precheck = self.equity_guard.require_verified_read(
                budget["equity_usd"], budget.get("equity_read_receipt"))
            self.store.update(press, "reasoning", risk_assessment={
                "equity_monitor": equity_precheck})
            midpoint = (float(snapshot["core"]["best_bid"]) + float(snapshot["core"]["best_ask"])) / 2
            context = self._decision_context(exchange, collected, midpoint)
            # Strategy-specific history must be validated by the controller,
            # not by a dashboard toggle or a model-generated assertion.
            stage = "historical_data_integrity"
            levels = self._historical_levels(collected, midpoint)
            context["historical_levels"] = levels
            stage = "market_quality_pre_model"
            screen = self._pre_model_market_screen(snapshot, context)
            if screen is not None:
                context["local_market_screen"] = screen
            self.store.update(press, "reasoning", indicators=context)
            model_snapshot = {**snapshot, "indicators": context, "fire_execution_scope": {
                "environment": "delta-india-demo",
                "instrument": self.symbol + " perpetual futures",
                **budget,
                "attached_stop_loss_and_take_profit_required": True,
                "dynamic_leverage_enabled": True,
                "min_leverage": 1, "max_leverage": 20,
                "separate_learning_model_has_no_trade_authority": True,
                **self._additional_fire_scope(),
                # Broker-backed affordability always wins over policy/AI cap.
                "max_contracts_per_entry": self._max_contracts_for_entry(budget),
            }}
            stage = "save_model_input"
            self.store.record_model_input(press, model_snapshot)
            stage = "model_request"
            report = self.probe(dict(ROLES), lambda: model_snapshot)
            raw = (report.get("results") or {}).get("fire") or {}
            stage = "model_decision"
            if "decision" not in raw:
                self.store.update(press, "rejected_no_order", model_latency_ms=raw.get("latency_ms"),
                                  reason_code=decision_failure_code(raw.get("error"), stage=raw.get("error_stage")),
                                  orders_submitted=False, protection_verified=False)
                return
            try:
                plan = validate(raw["decision"], snapshot["core"], require_leverage=True)
            except PlanError as exc:
                # A failed second validation must be classified, not silently
                # collapsed into the ambiguous model_decision_failed reason.
                # This is before any broker order intent or mutation.
                self.store.update(
                    press, "rejected_no_order",
                    model_latency_ms=raw.get("latency_ms"),
                    reason_code=decision_failure_code(str(exc), stage="validation"),
                    orders_submitted=False, protection_verified=False)
                return
            if plan["direction"] == "WAIT":
                # The autonomous policy rejects a neutral model response even
                # if a stub or replay bypassed the GPT-6 prompt validator.
                # There is no fabricated broker entry or fallback order.
                self.store.update(
                    press, "rejected_no_order", model_latency_ms=raw.get("latency_ms"),
                    reason_code=("gpt6_wait_no_trade" if self._allow_wait_choice()
                                 else "autonomous_invalid_wait"),
                    thesis=str(raw.get("thesis") or raw["decision"].get("thesis") or "")[:350],
                    orders_submitted=False, protection_verified=False)
                return
            plan = self._normalize_plan(plan, context)
            self.store.update(
                press, "preflight", direction=plan["direction"], selected_leverage=plan["leverage"], model_latency_ms=raw.get("latency_ms"),
                contracts=plan["contracts"], stop_loss=plan["stop_loss"],
                take_profit=plan["take_profit"],
                snapshot_at=snapshot["collected_at"], decision_at=_now().isoformat(),
                decision_quote={k: snapshot["core"].get(k) for k in ("best_bid","best_ask")},
                thesis=str(raw.get("thesis") or "")[:350],
                **self._entry_sizing_record())
            stage = "contract_size"
            if not 1 <= plan["contracts"] <= self._max_contracts_for_entry(budget):
                raise FireTradeError("Order exceeds market budget")
            stage = "exchange_preflight"
            exchange_quote = _live_preflight(exchange, snapshot, plan)
            price = max(exchange_quote["mark"], exchange_quote["best_ask"])
            stage = "margin_budget_recheck"
            current_budget = self._entry_budget(exchange, product_id, price,
                                                planned_leverage=plan["leverage"])
            self.store.update(press, "preflight", budget=current_budget)
            if plan["contracts"] > current_budget["max_contracts_per_entry"]:
                raise FireTradeError("Live margin budget changed")
            stage = "portfolio_equity_limits_recheck"
            equity_recheck = self.equity_guard.require_verified_read(
                current_budget["equity_usd"], current_budget.get("equity_read_receipt"))
            stage = "risk_governor"
            risk_assessment = self._assess_risk(plan, current_budget, exchange_quote)
            self.store.update(press, "preflight", risk_assessment={
                **risk_assessment, "equity_monitor": equity_recheck})
            stage = "account_exposure_recheck"
            self._require_account_flat(exchange, product_id)
            stage = "leverage_sync"
            synchronize_leverage(exchange, product_id, plan["leverage"])
            # Recompute the final broker-verified budget after a leverage change.
            stage = "leverage_budget_recheck"
            final_budget = self._entry_budget(exchange, product_id, price)
            if final_budget["leverage"] != str(plan["leverage"]) or plan["contracts"] > final_budget["max_contracts_per_entry"]:
                raise FireTradeError("Verified leverage or margin budget changed")
            stage = "portfolio_equity_limits_final"
            equity_recheck = self.equity_guard.require_verified_read(
                final_budget["equity_usd"], final_budget.get("equity_read_receipt"))
            final_assessment = self._assess_risk(plan, final_budget, exchange_quote)
            self.store.update(press, "preflight", budget=final_budget, risk_assessment={
                **final_assessment, "equity_monitor": equity_recheck})
            # Final signed account-wide exposure check immediately before the
            # durable order-intent path, even when leverage was unchanged.
            stage = "account_exposure_final"
            self._require_account_flat(exchange, product_id)
            units = _dec(final_budget["contract_value"]) * plan["contracts"]
            estimated_entry = exchange_quote["best_ask" if plan["direction"] == "LONG" else "best_bid"]
            self.store.update(press, "submitting", sizing_estimate={
                "notional_usd": str(units * estimated_entry),
                "loss_at_stop_usd": str(units * abs(estimated_entry - _dec(plan["stop_loss"]))),
                # A nominal estimate only: tiered broker initial margin and
                # the actual wallet requirement are independently rechecked
                # at the chosen leverage before any exchange order.
                "nominal_initial_margin_usd": str(
                    units * estimated_entry / _dec(plan["leverage"])),
                "selected_leverage": plan["leverage"],
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
                liquidation_verified=receipt.get("liquidation_verified") is True,
                liquidation_price=receipt.get("liquidation_price"),
                exit_order_ids=receipt.get("exit_order_ids", {}), protected_at=receipt.get("protected_at"),
                orders_submitted=True)
        except Exception as exc:
            # Preserve existing retry semantics and safety gates.
            if not submitted:
                detail = ({"risk_rejection_detail": safe_risk_rejection_detail(exc)}
                          if stage == "risk_governor" else {})
                if (self.symbol == "BTCUSD" and detail.get(
                        "risk_rejection_detail") == "stop_distance_exceeds_target"):
                    proof = _pretrade_quote_distance_evidence(
                        snapshot["core"], exchange_quote, plan)
                    if proof:
                        detail["risk_quote_diagnostics"] = proof
                self.store.update(press, "rejected_no_order",
                                  reason_code=stage + "_failed",
                                  protection_verified=False,
                                  orders_submitted=False, **detail)
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
