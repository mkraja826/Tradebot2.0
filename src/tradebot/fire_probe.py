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
    "Choose a perpetual futures position for the exact symbol in core.ticker.symbol for this Delta India demo snapshot. "
    "Return only a JSON object with direction (LONG or SHORT), contracts (positive "
    "integer absolute target position size), stop_loss and take_profit (prices). "
    "Use these exact top-level keys: direction, contracts, stop_loss, take_profit, thesis. "
    "Use uppercase LONG or SHORT and an unquoted whole number for contracts. "
    "For LONG put stop_loss below best_bid and take_profit above best_ask; reverse these levels for SHORT. "
    "Include a thesis string giving one concise sentence of reasoning. "
    "Use available margin, contract value, current position and spread. "
    "If the supplied snapshot contains fire_execution_scope, strictly respect "
    "its max_contracts_per_entry and attached stop/target requirement. Choose the quantity within that ceiling based on your thesis, stop distance and estimated dollar loss at the stop; the ceiling is optional capacity. "
    "Do not invent leverage, margin or available contract balance."
)


def validate(decision, core):
    if not isinstance(decision, dict):
        raise PlanError("Expected an object")
    side = decision.get("direction")
    size = decision.get("contracts")
    if side not in ("LONG", "SHORT") or type(size) is not int or size < 1:
        raise PlanError("Invalid direction or contract count")
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
    return dict(direction=side, contracts=size, stop_loss=str(stop), take_profit=str(target))


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
    content = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def query(model):
        client = client_factory()
        start = monotonic()
        try:
            reply = client._call(TOPBILLING_CHAT_URL, body={
                "model": model, "messages": [{"role": "system", "content": INSTRUCTION},
                                             {"role": "user", "content": content}]}, timeout=60)
            choice = reply["choices"][0]
            if not isinstance(choice, dict):
                raise PlanError("Malformed Top Billing response")
            parsed = decision_payload(choice)
            decision = validate(parsed, snapshot["core"])
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
