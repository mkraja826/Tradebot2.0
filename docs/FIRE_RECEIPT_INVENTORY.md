# FIRE receipt inventory — local evidence coverage only

This incremental research command scans **existing local SQLite databases** for
BTCUSD and XAUTUSD FIRE receipts and for the presence of related financial
reconciliation reports. It makes no HTTP requests, no AI calls and no order
mutations; it cannot enable DEMO or live execution.

```bash
python -m tradebot.fire_inventory --data-dir data --limit 100
```

The output explicitly distinguishes:

- `locally_reported_no_order`: the durable FIRE receipt records both
  `rejected_no_order` and `orders_submitted=false`. This is a local statement,
  **not** proof that an exchange order does not exist.
- `locally_reported_flat`: a terminal flat receipt with
  `orders_submitted=true`. This does **not** prove current signed broker
  positions or absence of open orders.
- `requires_broker_review`: unknown, inconsistent or potentially open state.
- `local_financial_report_present`: at least one historical report for that
  FIRE key exists in the reconciliation ledger. **This does not establish a
  verified net result**; the separate `tradebot.fire_performance` verifier
  applies economic checks and always excludes uncertain reports.

The report includes per-market local counts, missing database names, locally
flat receipts lacking financial review, and reconciliation reports without
matching local receipts. It limits displayed example entries without changing
aggregate counts. A nonzero exit code reports unavailable or incomplete data.

## Integrity and scope

All database access uses SQLite read-only mode and `PRAGMA query_only`.
Missing files are never created; symlinked/untrusted inputs, invalid schemas,
corruption, invalid receipts and replaced files fail closed with sanitized error
codes. Each database is read as a transactionally consistent local snapshot;
**the three databases are not one atomic snapshot**, and this command does
not claim that all broker fills, outside manual trades, earlier FIRE archives
or currently open positions are represented.

Run only on an approved private data directory. The command prints FIRE IDs and
local status metadata; do not publish operator results with sensitive context.

### Follow-up work

1. Reconcile all potentially open/unknown trades against fresh authenticated
   broker positions, orders, fills and wallet postings.
2. Expand discovery of legacy/manual/emergency closes, incomplete partial fills
   and delayed funding adjustments without inventing broker ownership.
3. Add broker-confirmed inventory completeness and verified realized portfolio
   risk before any account-wide profitability or expectancy claims.
4. Keep Kimi and GPT-6 unable to promote local coverage reports into trading
   decisions or risk-limit changes.

This is source-only Milestone 3 groundwork. It does not complete broker
commissioning, alter risk policy, clear the Gold commissioning lock or authorize
any trading.
