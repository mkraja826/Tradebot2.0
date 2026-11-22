# M09 financial reconciliation: missing signed fill reference

## Verified live diagnostic (2026-11-22 UTC)

The newest eligible historical BTC demo FIRE receipt remains
`overlapping_external_postings` in the strict broker reconciliation.

The suspicious wallet posting is a commission in the same product and
within the original position interval. It carries a fill reference that
does not belong to the selected order/fill set.

An extra **signed GET only** account-wide fill lookup, over the same
bounded historical window, confirmed:
- the existing product-filtered fills agree with the unfiltered fills
- the single conflicting wallet fill reference is absent from the wider
  signed broker fill history
- no authenticated evidence establishes ownership of that commission

The new `financial_reference_crosscheck` and M09 read-only probe report
only counts and fixed reason codes; they never disclose IDs, wallet
amounts, credentials, or private broker responses.

## Recovery without inventing financial data

The historical receipt remains **unreconciled**. Do not estimate its
net P&L from gross fill movement; do not attribute the commission using
amount/time similarity; do not delete or rewrite its ledger evidence.

The immediate recovery path is:
1. Preserve the original historical trade and its unresolved P&L.
2. Pursue broker-provided wallet-transaction/fill-reference evidence if
   Delta eventually exposes it, then rerun the strict analyser.
3. Separately evaluate a *fresh* restricted BTC demo session with the
   existing signed-equity-receipt guard, retained observed peak, 15-minute
   validity and 0.5% session-loss cap, with all independent account,
   execution, liquidation, stop-loss and take-profit gates preserved.
4. Reconcile any subsequent demo fills with independent signed wallet
   and order evidence; do not claim verified net P&L if inputs are absent.

A supervised session risk check is **not** proof that the unresolved
historical trade's P&L is zero, nor permission for unattended trading.
`trade_authorized` and `safe_to_enable_fire` remain false.
