"""Explicit, journaled execution of capital-aware AI proposals on Delta India demo."""
import hashlib
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from .broker import DeltaDemo, BrokerError, error_detail
from .decision import validate, evaluate_report, MODEL_VARS
from .engine import Journal, Engine

LEVERAGE = 20

def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid numeric exchange field") from None
    if not result.is_finite() or result <= 0:
        raise ValueError("Expected finite positive number")
    return result

def product_for(broker, symbol):
    if symbol not in MODEL_VARS:
        raise ValueError("Unsupported demo market")
    product = broker.product(symbol)
    if product.get("symbol") != symbol or type(product.get("id")) is not int or product["id"] < 1:
        raise BrokerError("Exchange product identity mismatch")
    return product

def account_context(broker, symbol):
    product = product_for(broker, symbol)
    wallet = broker.wallet()
    # Preserve currencies and exchange units. Do not mislabel robo equity as free cash.
    fields = ("asset_symbol", "balance", "available_balance", "position_margin", "order_margin")
    rows = [{k: row[k] for k in fields if k in row} for row in wallet["result"]]
    if not rows:
        raise BrokerError("No wallet data")
    product_fields = ("id", "symbol", "contract_value", "contract_unit_currency",
                      "settling_asset", "quoting_asset", "tick_size", "contract_type", "notional_type")
    spec = {k: product[k] for k in product_fields if k in product}
    # Only financial context, not account identifiers or credentials.
    positions = broker.positions(product["id"])
    position_fields = ("product_id", "size", "entry_price", "margin", "liquidation_price")
    if isinstance(positions, dict):
        positions = [positions]
    return {"leverage": LEVERAGE, "wallets": rows, "product": spec,
            "positions": [{k: p[k] for k in position_fields if k in p} for p in positions],
            "exchange_wallet_meta": {k:v for k,v in wallet.get("meta",{}).items()
                                     if k in ("net_equity","robo_trading_equity")}}

@dataclass(frozen=True)
class BracketIntent:
    product_id: int
    side: str
    size: int
    leverage: int
    capital_allocation: float
    entry_reference: float
    stop_loss: float
    take_profit: float

def mark_evidence(ticker, symbol, intent, now_us):
    """Check exchange trigger-price geometry, not strategy or capital quality."""
    if not isinstance(ticker,dict) or ticker.get("symbol")!=symbol or ticker.get("product_id")!=intent.product_id:
        return {"status":"ticker_identity_unverified"}
    stamp=ticker.get("timestamp")
    if type(stamp) is not int or not 0<=now_us-stamp<=30_000_000:
        return {"status":"ticker_stale_or_invalid"}
    try:
        mark=number(ticker.get("mark_price"))
    except ValueError:
        return {"status":"mark_unavailable"}
    sl,tp=number(intent.stop_loss),number(intent.take_profit)
    valid=sl<mark<tp if intent.side=="buy" else tp<mark<sl
    return {"status":"compatible" if valid else "bracket_crossed_mark",
            "mark_price":str(mark),"timestamp_us":stamp,
            "age_ms":(now_us-stamp)//1000}

class DemoExecutor:
    def __init__(self, broker: DeltaDemo, journal: Journal):
        self.broker, self.journal = broker, journal

    def execute(self, result, *, account):
        if result.get("status") != "proposed":
            return {"status": "not_proposed"}
        symbol = result["symbol"]
        proposal = validate(result["proposal"], symbol, require_capital=True)
        if proposal["action"] == "no_trade":
            return {"status": "no_trade"}
        product = product_for(self.broker, symbol)
        if account["product"]["id"] != product["id"] or account["product"]["symbol"] != symbol:
            raise ValueError("Account context product mismatch")
        entry, sl, tp = (number(proposal[k]) for k in ("entry_reference","stop_loss","take_profit"))
        if not (sl < entry < tp if proposal["side"] == "buy" else tp < entry < sl):
            raise ValueError("SL/TP on incorrect side of reference entry")
        intent = BracketIntent(product["id"], proposal["side"], proposal["size"], LEVERAGE,
                               proposal["capital_allocation"], proposal["entry_reference"],
                               proposal["stop_loss"], proposal["take_profit"])
        decision_id = result["decision_id"]
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("Missing decision id")
        client_id = hashlib.sha256(("recover:" + decision_id).encode()).hexdigest()[:32]
        try:
            self.journal.begin(client_id, symbol, intent)
        except sqlite3.IntegrityError:
            return {"status": "already_recorded", "client_id": client_id}
        try:
            leverage = self.broker.set_order_leverage(product["id"])
            if number(leverage["leverage"]) != LEVERAGE:
                raise BrokerError("Exchange did not confirm 20x")
        except Exception as exc:
            self.journal.finish(client_id, "preparation_failed", error_detail(exc))
            return {"status": "preparation_failed", "client_id": client_id}
        # Bracket triggers are mark-price based. Validate a fresh demo mark
        # immediately before sending, without silently repricing AI choices.
        try:
            check=mark_evidence(self.broker.ticker(symbol),symbol,intent,time.time_ns()//1000)
        except Exception as exc:
            self.journal.finish(client_id,"preparation_failed",{"phase":"mark_quote",**error_detail(exc)})
            return {"status":"preparation_failed","client_id":client_id,"reason":"mark_quote_failed"}
        if check["status"]!="compatible":
            self.journal.finish(client_id,"preparation_failed",{"phase":"bracket_compatibility",**check})
            return {"status":"preparation_failed","client_id":client_id,"reason":check["status"]}
        try:
            receipt = self.broker.submit_bracket(intent, client_id)
            if not isinstance(receipt, dict) or receipt.get("id") is None:
                raise BrokerError("Order receipt missing id")
        except Exception as exc:
            self.journal.finish(client_id, "unknown", error_detail(exc))
            return {"status": "unknown", "client_id": client_id}
        receipt={**receipt,"recover_pre_submit_mark":check}
        self.journal.finish(client_id, "acknowledged", receipt)
        return {"status": "acknowledged", "client_id": client_id, "receipt": receipt}

    def reconcile(self):
        Engine(self.broker, None, self.journal).reconcile()

def evaluate_and_execute(report, decisions, provider, models, executor):
    if not report.get("signals"):
        return evaluate_report(report, decisions, provider, models)
    account = account_context(executor.broker, report["symbol"])
    result = evaluate_report(report, decisions, provider, models, account=account)
    return {"decision": result, "execution": executor.execute(result, account=account)}
