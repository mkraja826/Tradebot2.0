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
from tradebot.runner import BotRunner, RunnerConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Tradebot 2.0 (Delta India demo only)")
    parser.add_argument("command", choices=("status", "catalog", "snapshot", "balances", "preview", "run"))
    parser.add_argument("--include-balances", action="store_true",
                        help="Include signed read-only demo wallet balances in snapshot")
    parser.add_argument("--output", help="Save a complete snapshot or preview JSON to this path")
    parser.add_argument("--max-options", type=int, default=128,
                        help="Option quote context budget for preview (8-512)")
    parser.add_argument("--mode", choices=("observe", "demo"), default="observe",
                        help="Runner mode. Observe is the safe default.")
    parser.add_argument("--demo-execute", action="store_true",
                        help="Explicit permission for demo orders; requires env opt-in too")
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--ai-interval-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.demo_execute and (args.command != "run" or args.mode != "demo"):
        parser.error("--demo-execute is only valid with: run --mode demo")
    if args.command == "run" and args.mode == "demo":
        if not args.demo_execute or os.getenv("ENABLE_DEMO_ORDERS") != "true":
            parser.error(
                "Demo orders require --demo-execute and ENABLE_DEMO_ORDERS=true; "
                "supervise your first testnet session"
            )
        if not os.getenv("DELTA_DEMO_API_KEY") or not os.getenv("DELTA_DEMO_API_SECRET"):
            parser.error("Demo order mode requires demo-only key and secret")


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
        allow_orders=(args.command == "run" and args.mode == "demo"),
    )
    if args.command == "run":
        runner = BotRunner(
            exchange, AIPlanner(),
            config=RunnerConfig(mode=args.mode,
                                journal_path=os.getenv(
                                    "TRADEBOT_JOURNAL", "data/trades.jsonl"),
                                ai_interval_seconds=args.ai_interval_seconds,
                                poll_seconds=args.poll_seconds,
                                max_options=args.max_options),
        )
        print(json.dumps({
            "environment": exchange.base_url,
            "mode": args.mode,
            "orders": "DEMO ENABLED" if args.mode == "demo"
                      else "READ ONLY",
            "message": "Stop with Ctrl+C. Use process supervision for emergencies.",
        }), flush=True)
        runner.run_forever()
        return
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
