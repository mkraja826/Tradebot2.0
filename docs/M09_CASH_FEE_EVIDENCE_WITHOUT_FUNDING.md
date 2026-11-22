# M09 — cashflow and fee evidence before funding-total block

## Evidence and motivation (22 Nov 2026)

The operator confirmed from Delta India DEMO signed GET-only data:
- 3 historical parent/child order GETs, 2 fully normalized BTC fills
- 6 normalized wallet postings: 2 cashflow, 4 commission, 0 funding
- Each fill's `meta_data.new_position` exists but neither contains a
  `realized_funding` field
- The selected BTC trade had a ~63.19-minute elapsed entry-to-exit interval
  and crossed no assumed 00:00/08:00/16:00 UTC funding boundary, with both
  endpoints outside a 10-minute timing buffer
- The broker's CURRENT BTCUSD perpetual product configuration independently
  returned `product_specs.rate_exchange_interval=28800` (8 hours).
  Delta India support separately publishes 05:30/13:30/21:30 IST examples;
  see https://www.delta.exchange/support/solutions?articleId=80001183756
- The normal in-memory reconciliation still failed at
  `missing_broker_funding_total`. **No crossing and no funding wallet
  posting do not prove broker funding total was zero.** Current product
  settings do not prove that the same schedule existed historically.

Previously `analyse` stopped at missing funding before looking at wallet
cashflows and commissions. As a result, an unrelated fee or cashflow
mismatch would remain hidden behind the first funding error.

## Minimal fail-closed refinement

The `analyse` order is now:
1. Verify product, owned orders, signed fill quantities/position lifecycle,
   exit flatness, currency and cash/fees from the actual fills.
2. Verify complete signed wallet history, transaction ownership, no
   overlapping or unexplained postings, cashflow and commission postings.
3. Require broker-reported `realized_funding` explicitly; reject missing.
4. Match wallet funding postings to the verified broker total.
5. **Only if all stages pass**, compute verified net realized P&L.

No amount calculation, attribution scope, accounting tolerance or hard
fail-closed predicate was removed or relaxed. The final funding total
remains mandatory, not inferred from a timestamp, absent wallet entry or
a history candle. No account trading permissions or API calls changed.

The read-only `fire_reconciliation_phase_probe` now reports a diagnostic
boolean `cashflow_and_commission_consistency_proven_in_memory`.
It is TRUE **only** if (a) the existing analyzer completed, or (b) the
exact recognized `missing_broker_funding_total` exception occurred after
cash and fee matching. It remains FALSE for mismatched fees/cashflows or any
prior broker/schema error. Even when TRUE, the probe still reports:
`is_net_realized_pnl=false`, `funding_reconciled=false` (if missing),
`trade_authorized=false`, no durable financial report, and no account
ledger mutation.

This makes the next live read-only M09 result more informative without
claiming the selected trade has proved net P&L or that all historical
receipts are reconciled.

## Regression coverage

New synthetic no-network cases:
- missing funding total and otherwise correct wallet: missing funding
  remains a hard block; cashflow/fee-only consistency reported.
- missing funding AND cashflow mismatch: cashflow mismatch surfaced first,
  no in-memory proof flag and no net P&L.
- missing funding AND fee mismatch: fee mismatch surfaced first, no
  in-memory proof flag and no net P&L.
- missing funding AND unidentified tax/adjustment: unsupported adjustment
  fail-closed, no net P&L.
- full verified synthetic funding case still passes unchanged.

All original reconciliation and phase-probe suites plus repository CI must
pass before merging. This is a SOURCE-ONLY change; no production VM source
has been updated or services restarted in this PR.

## Operator next action after merged-main CI green

Gated source-only checkout update from prior main to new exact merged SHA,
run the two targeted offline regression suites, verify all protective
services and BTC/Gold FIRE disabled, then one signed read-only
`tradebot.fire_reconciliation_phase_probe --data-dir data` with DEMO keys
and `allow_orders=False`. Expect one of:
- `wallet_cashflow_mismatch` / `wallet_commission_mismatch` /
  `unattributed_wallet_posting`: other broker accounting issues found;
  investigate but DO NOT modify original history.
- `missing_broker_funding_total` with the new in-memory cash/fee flag true:
  cash and fees reconcile for the selected trade **only**, funding still
  unverified, net P&L still blocked.
- another stage/reason: follow the sanitized evidence, do not speculate.

No broker orders, original ledger mutations, Gold one-shot-lock edits,
data quarantine releases, FIRE enable or unguarded production service
changes allowed.

M07 next UTC weekly equity opening, M08 quarantined BTC candle sources,
M09 missing broker funding and remaining historical financial reviews,
M10 continuous SL/TP lifecycle and M11 final account risk checks all
remain M12 first supervised DEMO release blockers.
