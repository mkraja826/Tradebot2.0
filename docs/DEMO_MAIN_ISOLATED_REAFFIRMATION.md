# Delta India DEMO Main — one-time isolated-margin reaffirmation

## Explicit owner authorization
On 22 November 2026 the account owner explicitly approved **one** authenticated
Delta India DEMO Main-account Isolated-margin setting request. This approval
does **not** authorize BTC or XAUTUSD trade placement, leverage modification,
account transfers, wallet resets, new keys, dashboard enablement or automated
retries. Their DEMO UI shows Main / Isolated and confirms the Tb2.0 API key
belongs to Main (Read Data, Account and Trading). Another key was deleted.

## Official API contract (verified 22 November 2026)
[Delta India API — Change margin mode](https://docs.delta.exchange/#change-margin-mode):
authenticated `PUT /v2/users/margin_mode`, body exactly
`{"margin_mode":"isolated","subaccount_user_id":"<signed current user_id>"}`.
Successful result must explicitly match the current authenticated user ID
and `margin_mode == "isolated"`. The actual Main DEMO account has no child
subaccounts; `GET /v2/sub_accounts` returns `[]`. The older
`GET /v2/profile` route is deprecated for API-key access.

**IMPORTANT:** A successful PUT response proves that Delta accepted the
requested setting *at that moment*. It is not a durable independent GET
readback. The normal FIRE order gate must continue requiring authoritative
signed margin verification. No local fixture, UI label, historical receipt
or returned PUT acknowledgment may be hardcoded into the normal
`signed_account_margin_mode` helper as perpetual permission to trade.

## Staged, one-time, operator-only CLI
Staging and running this command is supervised account configuration; this
feature does not alter deployed source or restart the dashboard/watchdog.

On the approved original Google Cloud VM, after reviewing and staging the
merged source separately from the running original:

```bash
set +x
set -a
source "$HOME/.config/tradebot2/keys.env"
set +a
PYTHONPATH="$HOME/Tradebot2.0-release-stage/src" PYTHONDONTWRITEBYTECODE=1 \
"$HOME/Tradebot2.0/.venv/bin/python" \
-m tradebot.demo_main_isolated_reaffirm \
--data-dir "$HOME/Tradebot2.0/data"
```

Default is **GET-only** and reports
`status=awaiting_one_time_operator_confirmation` only if:
- local dashboard FIRE endpoints are both disabled;
- original dashboard, watchdog and equity monitor services are active;
- two authenticated, complete **account-wide** zero-exposure and zero-order
  snapshots (all Delta margined products; realtime BTC & Gold; all pages of
  pending/open orders) pass at least eleven seconds apart;
- signed trading preferences establish the same current user identity
  before and after the two samples, with no Main-subaccount contradiction;
- no previous attempt marker exists.

On a real, still-flat DEMO Main account **only after owner approval**, use
`--reaffirm-main-demo-isolated` in a real local interactive SSH session
and type exactly `REAFFIRM MAIN DEMO ISOLATED`. An exclusive, fsynced,
0600 mode `main-demo-isolated-reaffirm-once.lock` is written inside the
original private data directory **before** any network mutation. Never
delete that marker to retry an ambiguous outcome; investigate with Delta
support instead.

The separate write-capable client rejects all methods except one exact
authenticated `PUT /v2/users/margin_mode` with the identity-matched
`isolated` body. It explicitly rejects order POSTs, deletions, wallet
transfers, leverage changes and additional PUT attempts. The CLI prints
only sanitized status fields, no API credentials, user IDs or balances.

After PUT the script performs a signed `GET
/v2/users/trading_preferences` to detect an explicit current `margin_mode`
readback *if Delta actually supplies it*. If it remains absent, the result
will be `isolated_setting_acknowledged_readback_absent`; do not interpret
that as independent long-lived margin verification or authorization to
execute FIRE. A timeout after issuing PUT is unconfirmed and consumes the
one-time attempt. No automated retry.

## Next supervised BTC commission gate
If the one-time broker change is acknowledged, review the exact outcome
and determine a supported, narrow authenticated account-mode readback,
or an explicitly reviewed single-session attestation contract that cannot
survive position changes, account changes or reconfiguration. Thereafter
verify live account-wide flatness, margin/liquidation budget, SL/TP and
watchdog before any independently authorized order. Do not change the
normal margin fail-closed release gate merely to get an order submitted.
