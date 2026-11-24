"""Read-only Delta India Demo BTC fill evidence, WITHOUT trade attribution.

A confirmed broker fill is not enough to infer entry/exit matching, realized
profit, funding or whether the stop-loss was in place. This module never
queries or calls any AI model, and cannot submit/cancel orders.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.trade_memory import TradeMemory


def collect_fill_evidence(exchange, memory, *, now=None, lookback_hours=24):
    if (getattr(exchange, "base_url", None) != DEMO_API or
            getattr(exchange, "allow_orders", None) is not False):
        raise ValueError("Confirmed-fill evidence requires read-only Delta India Demo")
    if type(lookback_hours) is not int or not 1 <= lookback_hours <= 24:
        raise ValueError("Lookback must be 1..24 hours")
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("Use timezone-aware timestamps")
    end_us = int(instant.timestamp() * 1_000_000)
    start_us = int((instant - timedelta(hours=lookback_hours)).timestamp() * 1_000_000)
    fills = exchange.btc_fills(start_time_us=start_us, end_time_us=end_us)
    # The exchange method must provide a *complete* requested window; it
    # throws when pagination is incomplete. No partial evidence is committed.
    result = memory.ingest_unattributed_broker_fills(fills)
    return {**result, **memory.unattributed_fill_summary(),
            "source": "delta-india-demo-confirmed-fills",
            "orders_submitted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/trade-learning.sqlite")
    parser.add_argument("--lookback-hours", type=int, default=24)
    args = parser.parse_args(argv)
    exchange = DeltaDemo(api_key=os.environ.get("DELTA_DEMO_API_KEY", ""),
                         api_secret=os.environ.get("DELTA_DEMO_API_SECRET", ""),
                         allow_orders=False)
    memory = TradeMemory(args.database)
    try:
        summary = collect_fill_evidence(exchange, memory,
                                        lookback_hours=args.lookback_hours)
    except Exception as exc:
        # Never display upstream response bodies, credentials or order details.
        print(json.dumps({"status": "evidence_unavailable",
                          "orders_submitted": False,
                          "error_type": type(exc).__name__}))
        raise SystemExit(2) from None
    print(json.dumps(summary, separators=(",", ":")))


if __name__ == "__main__":
    main()
