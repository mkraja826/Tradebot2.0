"""GPT-6-only read-only Fire Mode commissioning against a demo snapshot."""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
from time import monotonic

from tradebot.ai import PlanError, TOPBILLING_CHAT_URL, TOPBILLING_MODELS_URL, TopBillingClient
from tradebot.delta import DeltaDemo

ROLES = {"fire": "tb-gpt-6"}
INSTRUCTION = (
    "Decide whether an actual perpetual futures trade is justified for the exact symbol in core.ticker.symbol. "
    "WAIT is a correct decision whenever evidence, cost, risk or entry quality is inadequate. "
    "For WAIT return direction WAIT, contracts 0, stop_loss null, take_profit null, leverage null, "
    "and a concise thesis explaining why no trade is justified. Never force an entry. "
    "Otherwise return only a JSON object with direction (LONG or SHORT), leverage (integer from 1 to 20), contracts (positive "
    "integer absolute target position size), stop_loss and take_profit (prices). "
    "Use these exact top-level keys: direction, leverage, contracts, stop_loss, take_profit, thesis. "
    "Use uppercase LONG or SHORT and an unquoted whole number for contracts. "
    "For LONG put stop_loss below best_bid and take_profit above best_ask; reverse these levels for SHORT. "
    "Include a thesis string giving one concise sentence of reasoning. "
    "When indicators are present, compare the 15-minute and hourly closes with their EMA20 and slopes. "
    "Use the UTC session candle-based VWAP and 5-minute ATR to assess entry extension and exit distances. "
    "For re-entry, use the signed move since the previous verified bracket exit and identify fresh evidence in the thesis. "
    "Use historical_levels for UTC current and previous day, Monday week, and calendar month extremes. "
    "Current periods are developing through the last completed candle. Swings are confirmed candidate "
    "support/resistance over seven days. Consider levels between entry and target and explain relevant breaks. "
    "Treat missing readings as unknown. "
    "Use available margin, contract value, current position and spread. "
    "If the supplied snapshot contains fire_execution_scope, strictly respect "
    "its max_contracts_per_entry and attached stop/target requirement. Choose the quantity within that ceiling based on your thesis, stop distance and estimated dollar loss at the stop; the ceiling is optional capacity. "
    "Use stop_loss and take_profit prices exactly aligned to core.ticker.tick_size; never assume off-tick prices will be accepted unchanged. "
    "Select leverage from 1x through 20x based on verified market volatility and stop distance; 20x is a hard cap, never a target. No model decision can override liquidation or risk controls. Do not invent available contract balance."
)


RESTRICTED_BTC_INSTRUCTION = (
    "This is one supervised BTCUSD Delta India DEMO attempt using exactly "
    "the last 24 hours of 5-minute local market history, not month or week "
    "highs/lows. The supplied 24h history is provisionally validated locally "
    "but not independently trade-price authenticated; when evidence is "
    "inadequate, choose WAIT. Never invent monthly or weekly statistics. "
    "Make no trade when spread, entry setup or risk is questionable. "
    "Return only one JSON object with keys direction, leverage, contracts, "
    "stop_loss, take_profit, thesis. Direction must be WAIT, LONG or SHORT. "
    "For WAIT use contracts=0, leverage=null, stop_loss=null, "
    "take_profit=null and explain why. For a trade choose exactly one "
    "contract and integer leverage 1..20, tick-aligned stop_loss and "
    "take_profit; LONG requires stop below best_bid and target above best_ask, "
    "SHORT the reverse. Evaluate 15-minute/hour EMA20, ATR5m, VWAP and the "
    "single true last_24h high/low only. Do not infer trade authority from "
    "model output. Risk checks, broker signed isolated margin, verified "
    "account-wide flatness and broker-side brackets are independent mandates."
)


def instruction_for_snapshot(snapshot):
    """Prevent an old six-period prompt from hallucinating withheld months."""
    if not isinstance(snapshot, dict):
        raise PlanError("Invalid FIRE snapshot")
    scope = snapshot.get("fire_execution_scope") or {}
    if not isinstance(scope, dict):
        raise PlanError("Invalid FIRE execution scope")
    version = scope.get("strategy_history_version")
    if version is None:
        return INSTRUCTION
    if version != "btc-demo-recent24h-v1":
        raise PlanError("Unsupported FIRE history scope")
    context = snapshot.get("indicators")
    levels = context.get("historical_levels") if isinstance(context, dict) else None
    periods = levels.get("periods") if isinstance(levels, dict) else None
    ticker = (snapshot.get("core") or {}).get("ticker")
    if (snapshot.get("environment") != "delta-india-demo"
            or not isinstance(ticker, dict)
            or ticker.get("symbol") != "BTCUSD"
            or scope.get("max_contracts_per_entry") != 1
            or scope.get("attached_stop_loss_and_take_profit_required") is not True
            or not isinstance(levels, dict)
            or levels.get("strategy_history_version") != version
            or levels.get("source") != "original_delta_demo_24h_5m_local_only"
            or type(periods) is not dict
            or set(periods) != {"last_24h"}
            or periods["last_24h"].get("quality_status") != "provisionally_valid"
            or periods["last_24h"].get("bars") != 288
            or periods["last_24h"].get("expected") != 288
            or any(context.get(k) is None
                   for k in ("ema_15m", "ema_1h", "atr_5m"))):
        raise PlanError("Unverified restricted BTC FIRE history")
    return RESTRICTED_BTC_INSTRUCTION


def validate(decision, core, *, require_leverage=False):
    if not isinstance(decision, dict):
        raise PlanError("Expected an object")
    side = decision.get("direction")
    size = decision.get("contracts")
    if side == "WAIT":
        reason = decision.get("thesis")
        if (type(size) is not int or size != 0
                or decision.get("stop_loss") is not None
                or decision.get("take_profit") is not None
                or decision.get("leverage") is not None
                or not isinstance(reason, str) or not reason.strip()):
            raise PlanError("Malformed WAIT decision")
        return dict(direction="WAIT", contracts=0,
                    stop_loss=None, take_profit=None)
    if side not in ("LONG", "SHORT") or type(size) is not int or size < 1:
        raise PlanError("Invalid direction or contract count")
    leverage = decision.get("leverage")
    if require_leverage or leverage is not None:
        if type(leverage) is not int or not 1 <= leverage <= 20:
            raise PlanError("Invalid proposed leverage (must be integer 1..20)")
    try:
        stop, target, bid, ask = (Decimal(str(v)) for v in (
            decision["stop_loss"], decision["take_profit"], core["best_bid"], core["best_ask"]))
    except (InvalidOperation, KeyError):
        raise PlanError("Missing or malformed price") from None
    if not all(v.is_finite() and v > 0 for v in (stop, target, bid, ask)):
        raise PlanError("Invalid price")
    lower, upper = (stop, target) if side == "LONG" else (target, stop)
    if not lower < bid <= ask < upper:
        raise PlanError("Exit prices must bracket the quote in the chosen direction")
    plan = dict(direction=side, contracts=size, stop_loss=str(stop), take_profit=str(target))
    if leverage is not None:
        plan["leverage"] = leverage
    return plan


def decision_failure_code(error):
    # Only known local errors and HTTP status numbers may enter public receipts.
    http = re.fullmatch(r"Top Billing API HTTP ([1-5][0-9]{2})", str(error))
    if http:
        return "provider_http_" + http[1]
    return {
        "Top Billing API network error": "provider_network_error",
        "Invalid Top Billing API JSON response": "provider_invalid_json",
        "Malformed Top Billing response": "provider_invalid_response",
        "Missing model content": "model_empty_response",
        "Truncated completion": "model_truncated_response",
        "Incomplete completion": "model_incomplete_response",
        "Malformed completion": "model_invalid_json",
        "Expected an object": "model_invalid_object",
        "Invalid direction or contract count": "model_invalid_direction_or_quantity",
        "Malformed WAIT decision": "model_invalid_wait",
        "Invalid proposed leverage (must be integer 1..20)": "model_invalid_leverage",
        "Missing or malformed price": "model_invalid_price",
        "Invalid price": "model_invalid_price",
        "Exit prices must bracket the quote in the chosen direction": "model_invalid_exit_levels",
    }.get(str(error), "model_decision_failed")


def decision_payload(choice):
    if choice.get("finish_reason") == "length":
        raise PlanError("Truncated completion")
    if choice.get("finish_reason") not in (None, "stop"):
        raise PlanError("Incomplete completion")
    answer = choice["message"]["content"]
    if not isinstance(answer, str) or not answer.strip():
        raise PlanError("Missing model content")
    answer = answer.strip()
    wrapped = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", answer, re.S | re.I)
    return json.loads(wrapped[1] if wrapped else answer)


def run_probe(routes, snapshot_loader, client_factory=TopBillingClient):
    # Only this exact route may spend AI credits for FIRE.
    # Do not accept stale environment overrides or a second model route.
    if routes != ROLES:
        raise PlanError("FIRE is locked to GPT-6 only")
    catalogue = client_factory()._call(TOPBILLING_MODELS_URL, timeout=15)
    available = {row["id"] for row in catalogue.get("data", []) if isinstance(row, dict) and "id" in row}
    missing = set(routes.values()) - available
    if missing:
        raise PlanError("Top Billing catalogue missing route(s): " + ", ".join(sorted(missing)))
    snapshot = snapshot_loader()
    instruction = instruction_for_snapshot(snapshot)
    content = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def query(model):
        client = client_factory()
        start = monotonic()
        try:
            reply = client._call(TOPBILLING_CHAT_URL, body={
                "model": model, "messages": [{"role": "system", "content": instruction},
                                             {"role": "user", "content": content}]}, timeout=60)
            choice = reply["choices"][0]
            if not isinstance(choice, dict):
                raise PlanError("Malformed Top Billing response")
            parsed = decision_payload(choice)
            decision = validate(parsed, snapshot["core"],
                                require_leverage=bool(snapshot.get("fire_execution_scope", {}).get("dynamic_leverage_enabled")))
            result = {"decision": decision, "usage": reply.get("usage"), "request_id": client.last_request_id}
            if isinstance(parsed.get("thesis"), str):
                result["thesis"] = parsed["thesis"][:350]
        except PlanError as exc:
            result = {"error": str(exc)}
        except (KeyError, IndexError, TypeError, ValueError):
            result = {"error": "Malformed completion"}
        return dict(result, model=model, latency_ms=round((monotonic() - start) * 1000))

    # Exactly one billable completion: GPT-6 FIRE. Kimi is never queried.
    fire_result = query(ROLES["fire"])
    return {"mode": "read-only probe", "collected_at": snapshot["collected_at"],
            "snapshot_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "results": {"fire": fire_result}}


def load_snapshot(symbol="BTCUSD"):
    if symbol != "BTCUSD":
        from tradebot.fire_market import FireMarket
        return FireMarket(symbol, api_key=os.environ["DELTA_DEMO_API_KEY"],
                          api_secret=os.environ["DELTA_DEMO_API_SECRET"]).snapshot()
    from tradebot.market import collect_market_snapshot

    exchange = DeltaDemo(api_key=os.environ["DELTA_DEMO_API_KEY"],
                         api_secret=os.environ["DELTA_DEMO_API_SECRET"])
    snapshot = collect_market_snapshot(exchange, include_balances=True)
    product_id = snapshot["core"]["ticker"]["product_id"]
    positions = [p for p in exchange.btc_positions() if str(p.get("product_id")) == str(product_id)]
    return {**{k: snapshot[k] for k in ("environment", "collected_at", "core", "technical", "demo_funds")},
            "position_contracts": sum(int(p["size"]) for p in positions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-models", action="store_true", help="List available model IDs without paid calls")
    args = parser.parse_args()
    if args.list_models:
        print("\n".join(sorted(r["id"] for r in TopBillingClient()._call(TOPBILLING_MODELS_URL)["data"])))
        return
    report = run_probe(dict(ROLES), load_snapshot)
    print(json.dumps(report, indent=2))
    if any("error" in row for row in report["results"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
