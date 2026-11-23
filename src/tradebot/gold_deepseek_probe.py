"""Gold isolated DEMO-only DeepSeek trade-decision adapter.

This route only generates validated research decisions. It can be injected into
a future Gold execution controller after separate account, equity, archive,
margin and protective-order commissioning. It cannot place broker orders.
BTC FIRE remains exclusively GPT-6.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from time import monotonic

from tradebot.ai import (
    PlanError, TOPBILLING_CHAT_URL, TOPBILLING_MODELS_URL,
    TopBillingClient,
)
from tradebot.fire_probe import decision_payload, validate

GOLD_MODEL = "tb-deepseek-v4-1-flash"
GOLD_ROLES = {"fire": GOLD_MODEL}
_GOLD_SYMBOL = "XAUTUSD"
_GOLD_PROMPT = (
    "Analyze ONLY the XAUTUSD perpetual futures contract on Delta India DEMO. "
    "This is Gold; never reuse BTC price levels, volatility, position sizes or "
    "other market assumptions. Distinguish exchange XAUTUSD from physical spot "
    "gold, and do not invent any independent price feed or macroeconomic news. "
    "Use only supplied price, order book, volume, trend, ATR, VWAP and "
    "historical market data. Missing, stale or contradictory evidence is "
    "unknown, not bullish or bearish proof. "
    "Return exactly one JSON object with direction, leverage, contracts, "
    "stop_loss, take_profit, thesis, and size_tier (small, medium, or large). "
    "For autonomous Gold DEMO use fixed 20x leverage. YOU select size_tier "
    "and the actual whole-contract quantity using market confidence, ATR, "
    "stop distance and broker verified affordability. The small, medium, "
    "large guidelines target 5%, 20%, 40% of equity as POSITION NOTIONAL; "
    "they are NOT mandatory or hardcoded contract assignments. Use "
    "fire_execution_scope.notional_per_contract_usd to estimate size. "
    "The engine does not adjust your chosen contracts. "
    "Whole contracts, independent account exposure, max 20% equity as "
    "initial margin and exact attached SL/TP remain mandatory. "
    "Direction is WAIT, LONG or SHORT. "
    "For WAIT set contracts=0, leverage=null, stop_loss=null and "
    "take_profit=null. For directional candidates use integer contracts "
    "no larger than fire_execution_scope.max_contracts_per_entry and "
    "integer leverage exactly 20 for this isolated autonomous worker. "
    "Stop-loss and take-profit must bracket current "
    "bid/ask in the correct direction and use the broker product tick_size. "
    "Require absolute(executable_entry-stop_loss) <= "
    "absolute(take_profit-executable_entry): best_ask for LONG, "
    "best_bid for SHORT. This minimum gross 1:1 distance is "
    "a hard broker risk gate, not a warning. "
    "Explain the strongest evidence and uncertainty in the thesis. "
    "Model output is never an order permit. The independent broker checks "
    "must verify margin, liquidation, whole-account flatness, exact stop and "
    "target orders, and protection during the entire trade."
)


def validate_gold_isolated_snapshot(snapshot, *, now=None):
    """Reject wrong account/market and unfinished broker evidence pre-AI."""
    if not isinstance(snapshot, dict):
        raise PlanError("Gold decision snapshot invalid")
    core = snapshot.get("core")
    ticker = core.get("ticker") if isinstance(core, dict) else None
    scope = snapshot.get("fire_execution_scope")
    if (snapshot.get("environment") != "delta-india-demo"
            or not isinstance(ticker, dict)
            or ticker.get("symbol") != _GOLD_SYMBOL
            or ticker.get("contract_type") != "perpetual_futures"
            or not isinstance(scope, dict)
            or scope.get("expected_isolated_demo_subaccount") != "GOLD"
            or scope.get("signed_subaccount_isolated_verified") is not True
            or scope.get("broker_account_flat_verified") is not True
            or scope.get("attached_stop_loss_and_take_profit_required") is not True
            or scope.get("market_data_verified") is not True
            or scope.get("trade_authorized") is not False
            or type(scope.get("max_contracts_per_entry")) is not int
            or not 1 <= scope["max_contracts_per_entry"] <= (
                64 if scope.get("fixed_leverage") == 20 else 6)):
        raise PlanError("Gold isolated broker and market prerequisites unavailable")
    observed = snapshot.get("collected_at")
    if not isinstance(observed, str):
        raise PlanError("Gold price timestamp missing")
    try:
        at = datetime.fromisoformat(observed)
        current = now or datetime.now(timezone.utc)
        age = (current - at).total_seconds()
        bid = Decimal(str(core["best_bid"]))
        ask = Decimal(str(core["best_ask"]))
        tick = Decimal(str(ticker["tick_size"]))
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError):
        raise PlanError("Gold quote evidence malformed") from None
    if (at.tzinfo is None or at.utcoffset() is None
            or current.tzinfo is None or current.utcoffset() is None
            or not -5 <= age <= 60
            or not all(v.is_finite() and v > 0 for v in (bid, ask, tick))
            or bid >= ask or (ask-bid)/bid > Decimal("0.005")):
        raise PlanError("Gold broker quote stale or invalid")
    return scope


def run_gold_deepseek_probe(routes, snapshot_loader,
                            client_factory=TopBillingClient):
    """Exactly one Gold-only DeepSeek completion, never a broker order."""
    if routes != GOLD_ROLES:
        raise PlanError("Gold route must use DeepSeek only")
    snapshot = snapshot_loader()
    scope = validate_gold_isolated_snapshot(snapshot)
    content = json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                         allow_nan=False)
    catalogue = client_factory()._call(TOPBILLING_MODELS_URL, timeout=15)
    if (not isinstance(catalogue, dict)
            or not isinstance(catalogue.get("data"), list)
            or GOLD_MODEL not in {entry.get("id") for entry in catalogue["data"]
                                  if isinstance(entry, dict)}):
        raise PlanError("Gold DeepSeek model route not available")
    autonomous = scope.get("unattended_demo_mode") is True
    if autonomous and scope.get("one_attempt_operator_supervision_required") is not False:
        raise PlanError("Gold unattended scope not commissioned")
    instruction = _GOLD_PROMPT + (
        " In this isolated Gold DEMO experimental unattended mode, "
        "a valid eligible snapshot requires one directional candidate. "
        "Never return WAIT; choose the better supported LONG or SHORT. "
        "Choose integer contract quantity independently from evidence, "
        "volatility and the supplied broker affordability limit. "
        "Use the small/medium/large guidelines to select your own quantity; "
        "no automatic allocation or silent resizing is applied. "
        "The demo safety cap and signed margin affordability still apply. "
        "Chart-selected stop and target must be tick aligned and the "
        "gross target distance must be >= stop distance from the "
        "executable ask for LONG or bid for SHORT. "
        "Prefer a gross target distance at least 1.5 times the stop distance "
        "when chart structure supports it, leaving buffer for quote movements "
        "between decision and broker pre-order validation. Calculate both "
        "distances explicitly using executable best_ask for LONG or "
        "best_bid for SHORT and preserve correct tick alignment. "
        "Do not invent distant chart targets merely to satisfy this "
        "preference; broker's mandatory minimum 1:1 gate remains unchanged. "
        "Unknown or invalid market evidence is rejected by broker gates, "
        "not guessed by the model."
        if autonomous else "")
    start = monotonic()
    client = client_factory()
    stage = "provider_request"
    try:
        reply = client._call(TOPBILLING_CHAT_URL, body={
            "model": GOLD_MODEL,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": content},
            ],
        }, timeout=60)
        stage = "completion"
        choice = reply["choices"][0]
        parsed = decision_payload(choice)
        stage = "validation"
        decision = validate(parsed, snapshot["core"], require_leverage=True)
        if autonomous and decision["direction"] == "WAIT":
            raise PlanError("Gold unattended WAIT prohibited")
        if decision["direction"] != "WAIT":
            if decision["contracts"] > scope["max_contracts_per_entry"]:
                raise PlanError("Gold model exceeds verified contract limit")
            tick = Decimal(str(snapshot["core"]["ticker"]["tick_size"]))
            for key in ("stop_loss", "take_profit"):
                if Decimal(decision[key]) % tick != 0:
                    raise PlanError("Gold exit not aligned with broker tick")
        result = {
            "decision": decision,
            "usage": reply.get("usage"),
            "request_id": client.last_request_id,
        }
        if isinstance(parsed.get("thesis"), str):
            result["thesis"] = parsed["thesis"][:350]
    except PlanError as exc:
        result = {"error": str(exc), "error_stage": stage}
    except (KeyError, IndexError, TypeError, ValueError):
        result = {"error": "Malformed completion", "error_stage": stage}
    return {
        "mode": "read_only_gold_isolated_deepseek_decision",
        "collected_at": snapshot["collected_at"],
        "snapshot_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "results": {"fire": {
            **result, "model": GOLD_MODEL,
            "latency_ms": round((monotonic() - start) * 1000),
            "trade_authorized": False,
        }},
        "broker_order_mutations": False,
        "trade_authorized": False,
    }
