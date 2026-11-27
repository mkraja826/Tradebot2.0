# Gold V2 clean-slate replacement

Base: recover/gold-volatility-trail (repository candidate, not verified deployed SHA).
Scope: XAUTUSD demo only. The new modules do not import legacy strategy signals.
BTC, exchange execution, account isolation, lifecycle, history and dashboard remain unchanged.

## Current alpha
- gold_v2_engine: closed 5m/15m/1h candles, independent EMA/ATR regime and three signal families.
- gold_v2_scan: public demo-only feed, converts candle open timestamps to close timestamps.
- gold_v2_replay: hypothetical next-bar entry outcomes, round-trip cost scenario, explicit gaps and ambiguous bars.

Run from repository root:
    python3 -m unittest discover -s tests -p 'test_gold_v2*.py' -v
    python3 -m recover_trading.gold_v2_scan --once

The second command makes public read-only network requests. No credentials or orders.
The replay is a per-candidate primitive, not a complete prospective ledger, broker fill simulator,
or validated performance result. ATR multipliers, cost, and horizon are research assumptions.
Extreme candle checks currently flag only the latest range; earlier anomalous bars need independent review.

## Before replacement
1. Add point-in-time macro context, sessions, independent reference and full data-quality checks.
2. Add durable opportunity journal and non-overlapping validation, with at least 1000 observed opportunities.
3. Add tested position and exit management, realistic fees/funding/spread, and account isolation tests.
4. Review exact deployed revision; wire V2 exclusively into XAUTUSD, retiring legacy Gold entry routing.
5. Verify no active Gold exposure or unresolved orders before switching ownership; keep rollback revision.
6. Run full regression suite, verify BTC unchanged, and separately authorize demo deployment.

No production account access. No running service changes in this branch.
