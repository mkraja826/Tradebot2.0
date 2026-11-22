# BTC restricted DEMO — repeatable signed two-sweep account diagnostic

This module exists because the signed Delta Main isolated-margin setting
cannot currently be proved through the available account preference and
subaccount GET responses, while an older one-time margin-setting marker
already exists and must not be deleted or replayed.

`tradebot.btc_readonly_account_sweep.observe_flat_twice` uses:
- signed current-user identity reads before and after two account samples
- complete signed margined-position view for ALL products
- paginated signed account-wide open/pending order checks
- independent live-position queries for BTCUSD and XAUTUSD
- a monotonic interval of 11 to 40 seconds between samples

If user identity changes, either sample is incomplete/nonflat, or a signed
preference contradicts isolated margin, the diagnostic fails closed.

A live GET-only run on 2026-11-22 UTC observed the same account identity
and two flat account-wide snapshots. No order or settings mutation occurred.
This is time-sensitive evidence, not a permanent flatness certificate.

The output keeps `broker_margin_verified=false`,
`financial_reconciliation_verified=false`,
`trade_authorized=false`, and `safe_to_enable_fire=false`.

The older single-use margin-settings marker is not modified.
The existing FIRE signed margin and current exposure checks remain unchanged.
Any future authorized supervised attempt must revalidate live exposure,
margin, wallet equity, liquidation and bracket protections at that moment.
