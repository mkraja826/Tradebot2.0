# Broker exposure inventory — read-only DEMO diagnostic

This experimental Milestone 3 tool extends the local FIRE receipt inventory in
PR #5 with **two authenticated Delta India DEMO GET sweeps**, separated by
**at least 11 measured monotonic seconds**. It is not a commissioning
authorization, broker-ledger reconciliation or a real-time market-data feed.

Run only on an operator-controlled VM with a valid read-only DEMO API identity,
working network access, and the existing receipt directory:

```bash
python -m tradebot.fire_broker_inventory --data-dir data
```

The program does **not** call GPT-6, DeepSeek or Kimi, does not submit or
cancel orders, does not modify leverage, and never writes or repairs SQLite.
The Delta client is constructed with `allow_orders=False`, and the
observation function independently rejects every other mode.

## Observations

For both sweeps the tool uses authenticated GETs to inspect:

- The DEMO account's isolated-margin setting.
- The account-wide `/v2/positions/margined` list, acknowledging its
  documented potential settlement lag.
- **All pages** of account-wide open/pending orders with strict cursor and
  order-ID checks; unrelated products are not silently filtered out.
- Independently identified BTCUSD and XAUTUSD perpetual products and their
  real-time product-filtered positions.
- Existing local FIRE receipt and financial-review *coverage*, using the
  read-only inventory in PR #5. An unresolved or missing local receipt ledger
  remains a blocker even if the broker snapshots look flat.
- Durable `fire_entries` entry-intent states, independently checked even when
  their parent FIRE request claims `flat_verified` or `rejected_no_order`.
  An unconfirmed, accepted or submitting entry prevents a clean observation;
  a no-order request with **any** linked durable entry is contradictory.
- An internal SHA-256 fingerprint of all local receipt rows, entry-intent rows,
  reconciliation reports, available source fill/posting evidence, ownership
  claims and file identities before and after the broker observations. This
  catches equal-count, equal-status changes that the summary view cannot
  distinguish. Nonempty reconciliation reports require both the `evidence`
  and `claims` source tables; otherwise observation fails closed. A fingerprint
  is not a broker signature and does not guarantee atomicity across databases
  or capture every intermediate state between the two reads.

Both observations must be flat, isolated, consistent and stable. A changed
product ID, mismatch between margined and filtered positions, open unrelated
order, failed pagination, delayed/failed sample, or local-history change
produces a sanitized blocker. The output contains counts and signed quantity
strings but **no credentials, order IDs, unredacted provider error messages,
or financial amounts**.

A result of `two_flat_snapshots_observed_not_trade_authority` means only that
two bounded GET snapshots matched these checks. It is **not**:
- a declaration that the account will remain flat;
- a grant to enable FIRE, unlock Gold, stage/restart services or alter leverage;
- verification of historical fills, cancellations, partial fills, commissions,
  funding postings, manual trades, account realized P&L or profit expectancy;
- broker-signed per-response timestamp proof. HMAC request authentication
  does not cryptographically attest the server's response body.

No genuine broker account was queried or commissioned while implementing this
feature. Before interpreting actual operator results, independently confirm
the VM SHA, broker credentials/endpoint, operations watchdog, runtime equity
checkpoints, clock synchronization, and complete trade/lifecycle records.

## Development state

This source-only increment is intentionally based on PR #5 and should be
reviewed and merged **after** PR #5. Risk PR #3, commissioning PR #4, and
their independent human deployment gates remain separate. Offline tests use
mocked responses and temporary SQLite ledgers, never a real account.
