# Read-only account exposure when Delta DEMO subaccount listing is empty

## Observed incident

On the original authenticated Delta India DEMO VM (22 November 2026):
- Signed `GET /v2/users/trading_preferences` succeeded.
- Signed `GET /v2/sub_accounts` succeeded but returned **zero rows**.
- The strict account-margin helper therefore correctly rejected the result
  with `signed_current_account_margin_mode_unavailable` (zero matches, not duplicates).
- Both BTCUSD and XAUTUSD leverage settings were read back as 20x, but margin
  mode, position sizes and account-wide pending orders were UNKNOWN.

Official Delta documentation notes that `GET /v2/sub_accounts` lists
subaccounts for the parent user and should be called from the parent
account. An empty list does **not** mean the API-key account is isolated,
does **not** mean there are zero positions, and does not prove the key
belongs to any particular account type.

## Independent nonauthorizing exposure probe

This diagnostic deliberately **does not call** the margin-mode helper,
`/v2/profile` or `/v2/sub_accounts`. It makes only signed Delta India
DEMO GET requests from the approved VM:

1. `/v2/positions/margined` without product filtering, rejecting incomplete
   pagination or malformed/duplicated active contract-size evidence
2. `/v2/orders?states=open,pending`, exhaustively following the signed
   pagination cursor, including open orders on unrelated products
3. `/v2/products/BTCUSD` and `/v2/products/XAUTUSD` to verify actual
   broker product identities
4. Per-product signed real-time positions for BTC and Gold, checked against
   signed margined positions for disagreement

Only counts and BTC/Gold signed contract quantities are printed. Broker IDs,
wallet amounts, credentials, private profile fields and response/error bodies
must not appear in the output. On ANY error the probe reports a fixed
unverified blocker and removes partial counts.

### Operator command from original VM

The reviewed code is staged in a separate detached worktree, not currently
deployed to the active services. Run the module under the approved VM's
current DEMO credentials; **never** on a GitHub-hosted runner whose source
IP is not whitelisted:

```bash
(
  set +x
  set -a
  . "$HOME/.config/tradebot2/keys.env"
  set +a
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$HOME/Tradebot2.0-release-stage/src" \
  "$HOME/Tradebot2.0/.venv/bin/python" \
    -m tradebot.fire_exposure_only_probe
)
systemctl is-active tradebot2-fire-watchdog.service
```

The module is strictly read-only with `allow_orders=False`. A reported
zero position/order count is only **one point-in-time observation**. No
result will set `margin_mode_verified`, `two_sweep_flatness_verified`,
`safe_to_deploy`, `trade_authorized` or `safe_to_enable_fire` to true.

## Remaining release requirements

- Confirm margin mode from a genuinely authenticated, account-scoped source
  or a separately reviewed provider-attested operator process. Never infer
  it from zero subaccount rows, zero positions or 20x leverage.
- Independently repeat full-account signed observations with verified
  elapsed spacing, and ensure local original reconciled FIRE evidence exists.
- Resolve missing `fire-reconciliation.sqlite` without inventing historical
  wallet ownership or changing original BTC/Gold/wallet ledgers.
- Verify current UTC equity checkpoints, BTC/Gold historical extremes,
  watchdog/off-host alerts, VM code provenance and independent approval.

No margin change, order POST, cancel, source deployment, protective service
restart or production account access is part of this audit.
