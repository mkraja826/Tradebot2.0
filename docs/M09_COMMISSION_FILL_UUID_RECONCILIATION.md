# M09: strict broker fill UUID linkage for wallet commission postings

## Grounded broker observation

Original approved Delta India DEMO VM (22 Nov 2026) retrieved 3 signed
orders, 3 signed BTC fills, 6 signed wallet transactions for a historical
BTC FIRE. Two post-last-fill same-product wallet postings lacked normalized
order/fill references: one `commission`, one `cashflow`.

The strictly structural, GET-only inspection found `fill_uuid` on the
commission's raw `meta_data`, but **no recognized reference** on the
cashflow. Presence of `fill_uuid` was not by itself identity proof.

Delta's documented fill schema uses a broker-supplied UUID as the signed
fill's `id`. The *only* new linkage rule is:
- The source must be the broker's original signed commission posting.
- Its `fill_uuid` must be a valid UUID and agree with any simultaneous
  explicit `fill_id` (including top-level vs metadata identity).
- Its canonical ID must match **exactly** a signed fill returned in the
  bounded historical product-fill GET; that fill must be owned by a real
  order recorded in the originally verified receipt.
- The existing financial analyser still checks selected-order membership,
  product identity, quantity, lifecycle, fees, cashflow and funding.
- Any mismatch, unrelated fill, duplicate/conflicting source identity or
  ambiguous post-fill cashflow **continues to block** reconciliation.

No other wallet posting type is allowed to inherit the commission's
`fill_uuid` reference. In particular, the remaining cashflow posting must
be linked from an authoritative broker record; equal price/amount/time is
not an acceptable ownership join. No inferred/net-profit value or historical
claim is manufactured and the original `fire-reconciliation.sqlite` is not
created by this patch.

## Deployment

This source-compatible fix can be validated by full offline CI without
using broker credentials, creating a wallet ledger, calling paid AI,
changing risk settings or placing trades.

After review and a separate non-disruptive source-stage update on the VM,
re-run the original bounded, GET-only
`tradebot.fire_reconciliation_phase_probe --fire-id <original BTC ID>`.
Only if all original broker references (including cashflow and funding)
become provable may the separately reviewed durable reconciliation code
produce a financial statement. Until then, `is_net_realized_pnl` and
`safe_to_enable_fire` remain false.

This patch does **not** remedy programmatic isolated-margin verification,
missing reconciliation reports, BTC/Gold historical quality, authenticated
opening-equity checkpoints, watchdog runtime deployment or independently
verified off-host alert delivery.

## Single-pass redacted wallet-reference evidence

The staged `tradebot.fire_reconciliation_phase_probe` now performs a
supplementary *in-memory* structural check on the **same signed order,
fill and wallet transaction window** already fetched for strict accounting.
The new `wallet_reference_linkage_diagnostic` reports only:
- how many commission `fill_uuid` values match signed fills owned by the
  selected original trade, versus unmatched UUIDs;
- how many post-fill same-product cashflows still have no direct order/fill
  reference;
- a fixed allowlist of *field names*, never field values, from remaining
  cashflow metadata that might be relevant for a provider query;
- whether other unrecognized metadata fields are present.

It never prints transaction IDs, account IDs, UUID values, balances,
commissions, raw provider bodies or metadata values. A commission UUID match
alone is **not** sufficient to reconcile an unlinked cashflow. The printed
`financial_attribution_verified`, `all_unmatched_wallet_transactions_resolved`
and all trade authorization fields remain `false`, regardless of counts.

This lets one pre-approved VM GET-only diagnostic report both unresolved
wallet rows without requiring a separate manual metadata inspection after
every change. A lack of documented authoritative cashflow linkage requires
broker confirmation, not a timing or amount-based assumption.
