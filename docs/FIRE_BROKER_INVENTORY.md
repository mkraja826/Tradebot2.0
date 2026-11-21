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
  real-time product-filtered positions. For each FIRE product, compare the
  **exact signed contract quantity** from the account-wide margined response
  against the real-time filtered response. A same-direction quantity
  difference (e.g. +5 vs +3), opposite signs, or a nonzero/zero mismatch is
  inconsistent and blocks a clean result. Even quantities that agree but
  are nonzero remain blocked as active account exposure. Delta documents
  that margined data can lag, so equality is a diagnostic consistency check,
  not proof of synchronized broker snapshots.
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
  or capture every intermediate state between the two reads. Each individual
  SQLite file is read using a single bounded, read-only transaction covering
  its receipt/report, entry, and evidence/ownership tables; source device/inode
  is checked before and after. This avoids combining separate table reads
  from different moments within the same SQLite file.
- Local cross-table integrity checks require each stored ownership claim to
  reference an existing matching fill/posting evidence ID. Reports claiming
  net realized reconciliation must list existing fill and wallet-posting IDs
  owned by that same trade. Orphan claims, missing source events, mismatched
  embedded IDs, or claims unsupported by such reports block a clean result.
  These checks establish **local referential consistency only**, not
  authenticity or completeness of broker statements.

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

## Historical protective-child field check (one saved FIRE ID)

A separate **read-only**, bounded operator diagnostic is available to inspect
the actual Delta DEMO order fields for one *previously submitted* FIRE request.
It is not part of the order-enabled FIRE path and does not unlock anything.

```bash
python -m tradebot.fire_bracket_evidence \
  --data-dir data --symbol BTCUSD --fire-id <32-character-lowercase-hex-FIRE-ID>
```

For Gold, use `--symbol XAUTUSD`. This command first loads the selected
existing per-market SQLite store with a bounded read-only transaction and
device/inode checks; it never creates or edits a ledger. The stored receipt
must contain a submitted broker parent ID and two distinct saved child IDs,
a valid contract size, trade direction, and planned stop/take-profit triggers.
If a separate durable `fire_entries` record exists, the auditor now verifies
its **filled state, press ID, market symbol, parent order ID, original trade
direction, exact contract size and stop-loss/take-profit prices** against
the later parent FIRE receipt *before* fetching any broker orders. The
original entry product ID must also match the authenticated broker product
lookup before fetching the three historical orders. Missing or contradictory
entry-plan fields fail closed; local receipts are not exchange signatures.
Some older receipts may predate `fire_entries` and can still be inspected
against authenticated historical order fields, but this does **not** supply
the missing independent entry-intent evidence or prove continuous protection.

Only with a **DEMO read-only** client (`allow_orders=False`) does the diagnostic
make one authenticated `GET /v2/products/{symbol}` and **three**
`GET /v2/orders/{order_id}` lookups. Delta documents the by-ID endpoint and
the child order `size`, `stop_price`, `stop_order_type`, `bracket_order`,
`state`, `side`, and `product_id` fields:
https://docs.delta.exchange/

The command compares historical parent product/client ID, buy/sell direction,
full filled quantity and closed state. It additionally requires the parent
broker response to match FIRE's original **market-order, non-reduce-only entry**
with the saved attached bracket SL/TP prices, and requires a numerically
verified zero unfilled contract count. Both child orders must reference the
same product, opposite side, saved trigger, correct bracket type, **matching
contract size**, `mark_price` trigger method and explicit **reduce_only=true**.
Unknown or differently encoded broker fields fail closed for human schema
review; the operator must confirm Delta DEMO's actual bracket-child
`reduce_only` semantics before treating a clean result as comparable
historical evidence. Child states are summarized (open, pending, closed,
cancelled, unknown), without exposing broker account or order identifiers. Malformed, missing, changed or conflicting fields produce
sanitized blockers. Missing credentials or network access also block; errors
are not treated as negative broker responses. The diagnostic fingerprints
**all saved parent/entry rows and the source database's device/inode**, then
rechecks that read-only SQLite snapshot after the broker GETs. Changes,
replacement or loss of the local ledger during observation block a clean
field match, including changes to an unrelated historical receipt. This
ordinary SHA-256 comparison is a local consistency check, **not** a broker
signature or an atomic transaction with the exchange. Changes occurring
between the final local read and operator interpretation cannot be excluded.

Even a result of `historical_order_fields_match_not_protection_proof` is
**not** proof that both children were simultaneously active, that they
covered the position at every point in time, that any exit filled, that
the account is currently flat, or that the FIRE engine can be enabled.
Bracket quantities may change automatically with net positions. A separate
timestamped broker timeline, executed fill/cancel history, current account-wide
reconciliation, and independent operator approval remain necessary. Running
the command never submits, cancels or changes an order and never grants any
trade or recovery permission.

## Development state

This source-only increment is intentionally based on PR #5 and should be
reviewed and merged **after** PR #5. Risk PR #3, commissioning PR #4, and
their independent human deployment gates remain separate. Offline tests use
mocked responses and temporary SQLite ledgers, never a real account.
