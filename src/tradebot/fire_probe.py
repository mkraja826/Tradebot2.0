"""Read-only Fire Mode commissioning against an authenticated demo snapshot."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from time import monotonic

from tradebot.ai import PlanError, TOPBILLING_CHAT_URL, TOPBILLING_MODELS_URL, TopBillingClient
from tradebot.delta import DeltaDemo

ROLES = {"fire": "tb-kimi-k3-1-pro", "paper": "tb-gpt-6"}
INSTRUCTION = (
    "Choose a BTCUSD perpetual futures position for this Delta India demo snapshot. "
    "Return only a JSON object with direction (LONG or SHORT), contracts (positive "
    "integer absolute target position size), stop_loss and take_profit (prices). "
    "Use available margin, contract value, current position and spread."
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


def run_probe(routes, snapshot_loader, client_factory=TopBillingClient):
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
            answer = reply["choices"][0]["message"]["content"]
            decision = validate(json.loads(answer), snapshot["core"])
            result = {"decision": decision, "usage": reply.get("usage"), "request_id": client.last_request_id}
        except PlanError as exc:
            result = {"error": str(exc)}
        except (KeyError, IndexError, TypeError, ValueError):
            result = {"error": "Malformed completion"}
        return dict(result, model=model, latency_ms=round((monotonic() - start) * 1000))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {role: pool.submit(query, model) for role, model in routes.items()}
        return {"mode": "read-only probe", "collected_at": snapshot["collected_at"],
                "snapshot_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "results": {role: future.result() for role, future in futures.items()}}


def load_snapshot():
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
    routes = {role: os.getenv("TB_" + role.upper() + "_MODEL", model) for role, model in ROLES.items()}
    if len(set(routes.values())) != len(routes):
        raise SystemExit("Choose distinct Fire and paper models")
    report = run_probe(routes, load_snapshot)
    print(json.dumps(report, indent=2))
    if any("error" in row for row in report["results"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
