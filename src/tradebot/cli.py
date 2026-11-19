"""Read-only Delta India demo commands; CLI NEVER submits an order."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from tradebot.delta import DeltaDemo, DeltaError
from tradebot.market import collect_market_snapshot, MarketDataError
from tradebot.ai import AIPlanner, PlanError
from tradebot.decision import build_ai_context
from tradebot.journal import record, recent
from tradebot.session import session_phase, entry_phase, SessionPhase, NEW_YORK
from tradebot.runner import BotRunner, RunnerConfig
from tradebot.ledger import ingest_fills, fill_summary, record_equity
from datetime import timedelta


def main() -> None:
    parser = argparse.ArgumentParser(description="Tradebot 2.0 (Delta India demo only)")
    parser.add_argument("command", choices=("status", "catalog", "snapshot", "balances", "preview", "run", "reconcile", "ledger", "ai-check"))
    parser.add_argument("--include-balances", action="store_true",
                        help="Include signed read-only demo wallet balances in snapshot")
    parser.add_argument("--output", help="Save a complete snapshot or preview JSON to this path")
    parser.add_argument("--max-options", type=int, default=128,
                        help="Option quote context budget for preview (8-512)")
    parser.add_argument("--schedule", choices=("nyse", "crypto-24x7"), default="nyse",
                        help="Opt-in continuous crypto opportunity scan; default preserves NYSE hours")
    parser.add_argument("--max-hold-minutes", type=int, default=15,
                        help="24x7 demo pilot enforced maximum holding time: 1-60 minutes")
    parser.add_argument("--mode", choices=("observe", "demo"), default="observe",
                        help="Runner mode. Observe is the safe default.")
    parser.add_argument("--demo-execute", action="store_true",
                        help="Explicit permission for demo orders; requires env opt-in too")
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--ai-interval-seconds", type=int, default=300)
    parser.add_argument("--nyse-cash-scan-only", action="store_true",
                        help="Read-only DeepSeek scans only while NYSE cash market is open, including early closes")
    parser.add_argument("--lookback-hours", type=int, default=24,
                        help="1-168 hours of exchange fills to reconcile")
    parser.add_argument("--ledger-path", default="data/confirmed-fills.sqlite",
                        help="Local SQLite fill ledger (not committed)")
    args = parser.parse_args()
    if not 1 <= args.lookback_hours <= 168:
        parser.error("--lookback-hours must be 1..168")
    if not 1 <= args.max_hold_minutes <= 60:
        parser.error("--max-hold-minutes must be 1..60")
    if args.demo_execute and (args.command != "run" or args.mode != "demo"):
        parser.error("--demo-execute is only valid with: run --mode demo")
    if args.nyse_cash_scan_only and (
            args.command != "run" or args.mode != "observe" or args.schedule != "nyse"):
        parser.error("--nyse-cash-scan-only requires: run --mode observe --schedule nyse")
    if args.command == "run" and args.mode == "demo":
        if not args.demo_execute or os.getenv("ENABLE_DEMO_ORDERS") != "true":
            parser.error(
                "Demo orders require --demo-execute and ENABLE_DEMO_ORDERS=true; "
                "supervise your first testnet session"
            )
        if not os.getenv("DELTA_DEMO_API_KEY") or not os.getenv("DELTA_DEMO_API_SECRET"):
            parser.error("Demo order mode requires demo-only key and secret")


    if args.command == "run" and args.mode == "demo" and args.schedule == "crypto-24x7":
        if os.getenv("ALLOW_CRYPTO_24X7_DEMO") != "true":
            parser.error("24x7 demo execution requires separate ALLOW_CRYPTO_24X7_DEMO=true opt-in")

    if args.command == "ai-check":
        # Free read-only model access check; does not request a completion,
        # so it cannot spend model inference credits.
        planner = AIPlanner()
        can_use = planner.check_model_access()
        print(json.dumps({
            "provider": "topbilling",
            "model": planner.model,
            "accessible": can_use,
            "completion_requested": False,
            "orders_submitted": False,
        }, indent=2))
        return

    if args.command == "ledger":
        print(json.dumps(fill_summary(args.ledger_path), indent=2))
        return

    if args.command == "status":
        instant = datetime.now(timezone.utc)
        print(json.dumps({
            "environment": "delta-india-demo",
            "orders": "disabled-in-cli",
            "time_ny": instant.astimezone(NEW_YORK).isoformat(),
            "phase": session_phase(instant).value,
        }, indent=2))
        return

    if args.command == "preview":
        # An off-session proposal cannot be executed under NYSE entry rules.
        # Gate BEFORE even constructing a Delta client or fetching live quotes:
        # stale/offline demo tickers must never break our deterministic WAIT.
        instant = datetime.now(timezone.utc)
        phase = entry_phase(instant, schedule=args.schedule)
        if phase != SessionPhase.TRADING:
            output = {
                "environment": "delta-india-demo",
                "snapshot_at": None,
                "checked_at": instant.isoformat(),
                "session_phase": phase.value,
                "strategy": "WAIT",
                "rationale": "NYSE entry window is not open; no new positions are allowed.",
                "decision_source": "deterministic_session_gate_not_ai",
                "ai_called": False,
                "ai_tokens": {},
                "orders": [],
                "orders_submitted": False,
                "margin_verified": False,
                "warning": "Local safety rule. No market snapshot or AI inference requested.",
            }
            record(os.getenv("TRADEBOT_JOURNAL", "data/trades.jsonl"),
                   "session_gate_preview", {
                       "checked_at": instant.isoformat(),
                       "phase": phase.value,
                       "orders_submitted": False,
                   })
            if args.output:
                destination = Path(args.output)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(output, indent=2) + "\n",
                                       encoding="utf-8")
            print(json.dumps(output, indent=2))
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
                                max_options=args.max_options,
                                schedule=args.schedule,
                                nyse_cash_scan_only=args.nyse_cash_scan_only,
                                max_hold_seconds=args.max_hold_minutes * 60),
        )
        print(json.dumps({
            "environment": exchange.base_url,
            "mode": args.mode,
            "schedule": "nyse-cash-observe" if args.nyse_cash_scan_only else args.schedule,
            "orders": "DEMO ENABLED" if args.mode == "demo"
                      else "READ ONLY",
            "message": "Stop with Ctrl+C. Use process supervision for emergencies.",
        }), flush=True)
        runner.run_forever()
        return
    if args.command == "reconcile":
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=args.lookback_hours)
        fills = exchange.btc_fills(
            start_time_us=int(start.timestamp() * 1_000_000),
            end_time_us=int(end.timestamp() * 1_000_000),
        )
        persisted = ingest_fills(args.ledger_path, fills)
        equity = exchange.wallet_balances().get("meta", {}).get("net_equity")
        if equity is not None:
            record_equity(args.ledger_path, equity, at=end)
        print(json.dumps({
            "mode": "read_only_fill_reconciliation",
            "window_hours": args.lookback_hours,
            "fills": persisted,
            "summary": fill_summary(args.ledger_path),
            "order_placement_enabled": False,
        }, indent=2))
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

    try:
        snapshot = collect_market_snapshot(
            exchange, include_balances=args.include_balances or args.command == "preview")
    except (MarketDataError, DeltaError) as exc:
        if args.command != "preview":
            raise
        # Never create a model proposal based on stale/absent BTC quotes.
        # Explicitly report "unavailable", not a strategy chosen by DeepSeek.
        issue = str(exc) if isinstance(exc, MarketDataError) else (
            "Delta Demo read failed; check testnet market and account connectivity")
        output = {
            "environment": "delta-india-demo",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "session_phase": session_phase(datetime.now(timezone.utc)).value,
            "status": "market_data_unavailable",
            "decision_source": "data_validation_failed_not_ai",
            "ai_called": False,
            "error": issue,
            "orders": [],
            "orders_submitted": False,
            "margin_verified": False,
            "warning": "No valid live BTC snapshot; no AI request or order.",
        }
        record(os.getenv("TRADEBOT_JOURNAL", "data/trades.jsonl"),
               "market_data_preview_rejected", {
                   "reason": type(exc).__name__,
                   "orders_submitted": False,
               })
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(output, indent=2) + "\n",
                                   encoding="utf-8")
        print(json.dumps(output, indent=2))
        raise SystemExit(2) from None
    if args.command == "preview":
        if args.schedule == "crypto-24x7":
            # Override the NYSE label only for explicit 24/7 research; retain
            # actual market quote freshness checks and all order safety gates.
            snapshot["nyse_phase"] = snapshot["session_phase"]
            snapshot["session_phase"] = "trading"
            snapshot["trading_schedule"] = args.schedule
            snapshot["max_hold_seconds"] = args.max_hold_minutes * 60
        # A research proposal is never an order. When the NYSE entry window
        # is closed or flattening, do not spend an AI completion merely to
        # learn that opening new positions is forbidden by our local clock.
        path = os.getenv("TRADEBOT_JOURNAL", "data/trades.jsonl")
        invalid_ai_plan = False
        if snapshot["session_phase"] != "trading":
            output = {
                "environment": "delta-india-demo",
                "snapshot_at": snapshot["collected_at"],
                "session_phase": snapshot["session_phase"],
                "strategy": "WAIT",
                "rationale": "NYSE entry window is not open; no new positions are allowed.",
                "decision_source": "deterministic_session_gate_not_ai",
                "ai_called": False,
                "ai_tokens": {},
                "orders": [],
                "orders_submitted": False,
                "margin_verified": False,
                "warning": "Local safety rule, not an AI trading recommendation.",
            }
            record(path, "session_gate_preview", {
                "snapshot_at": snapshot["collected_at"],
                "phase": snapshot["session_phase"],
                "orders_submitted": False,
            })
        else:
            context, products = build_ai_context(
                snapshot, max_options=args.max_options)
            planner = AIPlanner()
            try:
                proposal = planner.propose(context, products, recent(path))
            except PlanError as exc:
                # Never convert an invalid completion into executable legs or
                # misrepresent it as the model deliberately choosing WAIT.
                invalid_ai_plan = True
                output = {
                    "environment": "delta-india-demo",
                    "snapshot_at": snapshot["collected_at"],
                    "session_phase": snapshot["session_phase"],
                    "status": "invalid_ai_response_no_plan",
                    "decision_source": "failed_ai_validation",
                    "ai_called": True,
                    "error": str(exc),
                    "finish_reason": planner.last_finish_reason,
                    "ai_tokens": {k: planner.last_usage[k] for k in
                                  ("prompt_tokens", "completion_tokens", "total_tokens")
                                  if isinstance(planner.last_usage, dict)
                                  and k in planner.last_usage},
                    "model": planner.model,
                    "orders": [],
                    "orders_submitted": False,
                    "margin_verified": False,
                    "warning": "No valid proposal. No retry; a completion may have incurred charges.",
                }
                record(path, "ai_preview_rejected", {
                    "snapshot_at": snapshot["collected_at"],
                    "reason": str(exc),
                    "finish_reason": planner.last_finish_reason,
                    "model": planner.model,
                    "ai_tokens": output["ai_tokens"],
                    "orders_submitted": False,
                })
            else:
                output = {
                    "environment": "delta-india-demo",
                    "snapshot_at": snapshot["collected_at"],
                    "session_phase": snapshot["session_phase"],
                    "trading_schedule": args.schedule,
                    "strategy": proposal.strategy,
                    "rationale": proposal.rationale,
                    "decision_source": "validated_ai_plan",
                    "ai_called": True,
                    "orders": [
                        {"product_id": o.product_id, "side": o.side, "size": o.size}
                        for o in proposal.orders
                    ],
                    "candidate_coverage": context["coverage"],
                    "model": planner.model,
                    "ai_tokens": {k: planner.last_usage[k] for k in
                                  ("prompt_tokens", "completion_tokens", "total_tokens")
                                  if isinstance(planner.last_usage, dict)
                                  and k in planner.last_usage},
                    "orders_submitted": False,
                    "margin_verified": False,
                    "warning": "Research proposal only. No broker order or P&L was produced.",
                }
                record(path, "ai_preview", {
                    "strategy": proposal.strategy,
                    "rationale": proposal.rationale,
                    "orders": output["orders"],
                    "snapshot_at": snapshot["collected_at"],
                    "model": planner.model,
                    "ai_tokens": output["ai_tokens"],
                })
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(output, indent=2) + "\n",
                                   encoding="utf-8")
        print(json.dumps(output, indent=2))
        if invalid_ai_plan:
            raise SystemExit(2)
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
