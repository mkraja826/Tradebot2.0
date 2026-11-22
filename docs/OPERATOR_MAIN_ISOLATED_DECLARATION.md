# Manual account configuration — Delta India Demo

The owner declares that the selected account is **Main**, and margin mode is
**Isolated**. The private VM file is:
`/home/support/.config/tradebot2/manual-account-mode.json` (0600, support-owned).

The read-only `tradebot.operator_account_mode.read_manual_mode` checks the
declaration, file ownership and permissions, demo environment, and the
30-day freshness limit. It does not call the broker API or use any paid AI.

The supervised BTC preflight exposes
`owner_declared_account_mode=owner_declared_not_broker_verified`.
It keeps `signed_isolated_margin_verified=false` if actual signed account
evidence is unavailable. This declaration **must not** enable new FIRE
entries, authorize restarts, replace broker account-wide checks, or assert
that the broker margin mode was independently verified.

When the owner changes the account or margin mode, update the private setting
and timestamp deliberately, after checking Delta's account UI. A non-isolated
or wrong-account configuration must not be accepted as isolated. Never commit
the private file, wallet data, API credentials, or account IDs.
