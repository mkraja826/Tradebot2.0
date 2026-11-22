# ChatGPT Tb2.0 equity checkpoint inspection

The stdio MCP plugin now exposes `equity_checkpoint_status()`: an exact,
read-only view of the existing dashboard's `GET /api/risk/checkpoints`.
It does not connect to the broker directly, modify risk ledgers, call paid
AI, create orders, or enable BTC/Gold FIRE.

The tool returns only the daily/weekly UTC checkpoint flags, current
freshness/integrity status, blocking/alert reason codes and next scheduled
opening windows. It excludes wallet values, account IDs, transport receipts
and API keys. It explicitly reports that it cannot authorize trading.

## Rollout prerequisite

Merge and test the source, then update the **existing plugin process** on the
VM using a reviewed service deployment after verifying no active exposure and
protective service continuity. A source merge does not update an already
running/registered MCP plugin instance; the client may need to reconnect.

A `healthy` checkpoint result is necessary but **insufficient** for
commissioning: M09 broker-wide financial evidence, BTC market-data quality,
leverage/margin proof, account-wide flatness, independent protective tests and
the final human supervised-DEMO release review all remain separate.
A missing or missed weekly checkpoint is never fabricated or backfilled.
