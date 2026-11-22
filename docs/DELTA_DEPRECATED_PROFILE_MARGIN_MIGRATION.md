# Delta India account margin-mode API migration — 2026-11

## Confirmed provider contract break

Delta India's official API documentation states in the **19 August 2026**
changelog that `GET /v2/profile` is no longer available to API keys. Four
Tradebot 2.0 components still read that endpoint and could never validate
isolated margin through current authenticated API requests:
`fire_account_guard.require_flat_demo_account`,
`fire_leverage_probe`, `fire_broker_inventory`, and
`fire_leverage.verify_liquidation_clearance`.

Official source: https://docs.delta.exchange/#changelog

## Supported signed evidence replacement

The currently documented:
- `GET /v2/users/trading_preferences`: account's signed `user_id`
- `GET /v2/sub_accounts`: array of signed account objects, with `id`
  and `margin_mode`

Official sources: https://docs.delta.exchange/#get-users-trading-preferences
and https://docs.delta.exchange/#get-subaccounts

The new `signed_account_margin_mode` helper matches the current signed
user ID against **exactly one** account object returned in the same API-key
scope. Any missing, duplicated, malformed or contradictory ID, missing
margin mode, untrusted/non-DEMO client or broker failure blocks readiness.
Only explicitly `isolated` is safe; `portfolio` and `cross` remain
ineligible. The full two signed GETs must both succeed; no fallbacks to
wallet balances, another account's margin mode or zero-position inference.

The read-only account audit continues to require
`allow_orders=False`. The separate already-authorized broker execution
controller may call this helper **after a fill** with its own DEMO-only
order-capable client, but the helper itself makes only signed GET requests.
It never changes margin, leverage, or any broker order.

A GitHub Actions read-only probe exposes only fixed diagnostic stage
names. It reports whether the documented current-user preferences signed
GET succeeds, and a permitted HTTP status code if it fails. No raw provider
response text, user identifiers, account IDs, credentials or balances appear
in the workflow logs.

## Main-account empty-subaccount readback correction (22 Nov 2026)

The approved original VM returned an authenticated empty `/v2/sub_accounts`
array for the DEMO Main account even though the account UI showed
`Main / Isolated`. This is not proof of margin state. Delta's separate
official MCP context describes `get_trading_preferences` as providing a margin
mode, but the public REST example does **not** guarantee such a field. If and
only if the actual signed `trading_preferences.result` contains a valid
explicit `margin_mode` for its own validated `user_id`, the helper can now
accept that **direct** current-user evidence despite zero matching
`sub_accounts` rows. It still performs both signed GETs, requires a valid
subaccount list and fails on duplicate, invalid or conflicting modes.

When preferences omit `margin_mode`, the existing two-endpoint strict behavior
remains and the main account's isolated mode is **unverified**. No inference
from `default_auto_topup`, the UI, zero balances, no positions, or another
user's subaccount is allowed. Signed direct `portfolio` or `cross` mode is
never translated into isolated. No API POST/PUT, account adjustment,
service restart, live trading or margin-mode override is introduced.

This is a conditional code path and **not** proof that the original DEMO VM
actually returns an explicit mode. After merge and separate staging, the
read-only `fire_leverage_probe` must establish the real broker result.

## Limitations and rollout

Delta documents `GET /v2/sub_accounts` for the parent/main user. If the
running key is scoped to a different subaccount and these two endpoints
cannot establish identity, the correct result is **BLOCKED**. Such a result
requires verified operator-supplied account evidence; never silently
fallback to a non-authenticated or non-scoped account record.

Even a passing broker margin proof does not clear the M09 financial ledger,
historical data quality, genuine equity checkpoints, two account-wide
broker sweeps, watchdog/alerts, or independent release sign-off.

No new trade, broker mutation, key rotation, paid AI, VM restart or manual
configuration adjustment was performed by this source migration.
