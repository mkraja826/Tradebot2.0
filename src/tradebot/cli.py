"""Read-only Delta India demo commands; CLI NEVER submits an order."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from tradebot.delta import DeltaDemo
from tradebot.market import collect_market_snapshot
from tradebot.ai import AIPlanner
from tradebot.decision import build_ai_context
from tradebot.journal import record, recent
from tradebot.session import session_phase, NEW_YORK


def main() -> None:
    parser = argparse.ArgumentParser(description="Tradebot 2.0 (Delta India demo only)")
    parser.add_argument("command", choices=("status", "catalog", "snapshot", "balances", "preview"))
    parser.add_argument("--include-balances", action="store_true",
                        help="Include signed read-only demo wallet balances in snapshot")
    parser.add_argument("--output", help="Save a complete snapshot or preview JSON to this path")
    parser.add_argument("--max-options", type=int, default=128,
                        help="Option quote context budget for preview (8-512)")
    args = parser.parse_args()

    if args.command == "status":
        instant = datetime.now(timezone.utc)
        print(json.dumps({
            "environment": "delta-india-demo",
            "orders": "disabled-in-cli",
            "time_ny": instant.astimezone(NEW_YORK).isoformat(),
            "phase": session_phase(instant).value,
        }, indent=2))
        return

    exchange = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    if args.command == "catalog":
        contracts = exchange.products()
        print(json.dumps({
            "environment": "delta-india-demo",
            "btc_derivative_count": len(contracts),
            "sample": [{"symbol": c["symbol"], "id": c["id"],
                        "contract_type": c["contract_type"]}
                       for c in contracts[:15]],
        }, indent=2))
        return

    if args.command == "balances":
        # Wallet balances are read-only; symbols are displayed separately.
        response = exchange.wallet_balances()
        wallets = [
            {"asset": w["asset_symbol"], "available_balance": w["available_balance"],
             "blocked_margin": w.get("blocked_margin")}
            for w in response["balances"]
        ]
        print(json.dumps({
            "environment": "delta-india-demo",
            "net_equity": response["meta"].get("net_equity"),
            "wallets": wallets,
        }, indent=2))
        return

    snapshot = collect_market_snapshot(
        exchange, include_balances=args.include_balances or args.command == "preview")
    if args.command == "preview":
        # Research-only: the model can choose any strategy, but nothing
        # produced here can place an exchange order.
        context, products = build_ai_context(
            snapshot, max_options=args.max_options)
        path = os.getenv("TRADEBOT_JOURNAL", "data/trades.jsonl")
        proposal = AIPlanner().propose(context, products, recent(path))
        output = {
            "environment": "delta-india-demo",
            "snapshot_at": snapshot["collected_at"],
            "session_phase": snapshot["session_phase"],
            "strategy": proposal.strategy,
            "rationale": proposal.rationale,
            "orders": [
                {"product_id": o.product_id, "side": o.side, "size": o.size}
                for o in proposal.orders
            ],
            "candidate_coverage": context["coverage"],
            "orders_submitted": False,
            "margin_verified": False,
            "warning": "Research proposal only. No broker order or P&L was produced.",
        }
        record(path, "ai_preview", {
            "strategy": proposal.strategy,
            "rationale": proposal.rationale,
            "orders": output["orders"],
            "snapshot_at": snapshot["collected_at"],
        })
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(output, indent=2) + "\n",
                                   encoding="utf-8")
        print(json.dumps(output, indent=2))
        return
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Files contain prices and potentially account balances, never secrets.
        destination.write_text(json.dumps(snapshot, indent=2) + "\n",
                               encoding="utf-8")
    print(json.dumps({
        "environment": snapshot["environment"],
        "timestamp": snapshot["collected_at"],
        "session_phase": snapshot["session_phase"],
        "btc_bid": snapshot["core"]["best_bid"],
        "btc_ask": snapshot["core"]["best_ask"],
        "futures": len(snapshot["futures"]),
        "options": len(snapshot["options"]),
        "quality": snapshot["quote_counts"],
        "demo_funds": snapshot["demo_funds"],
        "saved_to": args.output,
        "orders": "disabled-in-cli",
    }, indent=2))


if __name__ == "__main__":
    main()
