# BTCUSD DEMO operator evidence packet — read-only, not trade permission

The `tradebot.demo_release_evidence` module consolidates the existing
**read-only** DEMO release checks into one fixed-format, sanitized diagnostic.
It is an operational evidence collection aid, not a new order-execution entry
point, a replacement for independent broker-wide reconciliation, or evidence
that the operator has approved an order.

**This is staged candidate source only**. Do not run code from a draft review
branch on the live VM or change the deployed SHA without the approved staging
procedure. Once the code is independently reviewed, deployed with FIRE still
disabled, and operator access is available, run in the preserved original
Tradebot2.0 directory with the existing protected DEMO credentials:

```bash
cd ~/Tradebot2.0
PYTHONPATH="$PWD/src" "$PWD/.venv/bin/python" \
  -m tradebot.demo_release_evidence \
  --data-dir "$PWD/data" \
  --fire-id b7f242b10c584d6eacc831f9f713eaf8
```

That historical BTC FIRE identifier is a **previously saved** locally
`flat_verified` example, not a request for a new trade. First independently
confirm the same receipt exists in the **original** VM ledger. Do not invent
or replace a missing receipt. Never paste API secrets, private key paths,
raw request headers or complete broker replies into a public GitHub issue.

## What the command checks

1. Demo-only client with `allow_orders=False`; valid selected completed
   BTC FIRE identifier; trusted original nonsymlink data folder.
2. Clock sync from local `timedatectl`, active dashboard/watchdog/equity
   monitor services, and both dashboard FIRE endpoints explicitly disabled.
3. `fire-equity-risk.sqlite` read-only checkpoint health: authentic daily
   and weekly UTC openings and a fresh receipt-backed observation. A missing
   ledger, stale observation or missing historical opening blocks; the
   command does **not** create or repair original equity history.
4. Two independently timed (>=11-second interval) authenticated Delta
   India DEMO GET-only broker sweeps via `fire_broker_inventory`. The
   existing checker covers the whole account's margined positions/open
   orders, full pagination where advertised, both BTC/Gold realtime sizes,
   source-identity and local historical-coverage consistency.
5. Only if the account inventory is clean, compare **historical** BTC
   parent and SL/TP child order fields by exact broker ID via
   `fire_bracket_evidence`. An invalid, missing or ambiguous child
   triggers `historical_btc_bracket_fields_unverified`.
6. Repeat NTP, all three monitor-service checks, both disabled FIRE
   endpoints and read-only signed-equity checkpoint health after the broker
   sweeps and archived-order reads. Any late status/freshness change blocks
   even the limited read-only consistency result; this is not a guarantee
   that those states remain unchanged after the report.

Cheap host/ledger failures skip expensive broker calls. Any incomplete
broker inventory skips the historical order GETs. Exceptions are reduced
to fixed blocker codes, never passed through raw from exchange or systemd.

Output is one JSON object on stdout, with no account ID, order ID, saved
FIRE ID, wallet balances, fees, broker response bodies, API keys or raw error
messages. It records only limited counts, checkpoint/broker booleans and
sanitized blockers.

Even if `status` is
`limited_read_only_checks_consistent_not_execution_authority`, output
**always** has `trade_authorized=false`, `safe_to_enable_fire=false`,
`ready_for_unattended_trading=false` and
`independent_risk_review_required=true`. It never declares complete fill
and funding reconciliation, current wallet risk admission, continuous
historical protection, or a safe future account state.

## Still-required approvals and observations

- Independent security/risk reviews of source, ledger migration and release
  candidate, signed-wallet 2%/5%/8% limits and broker's actual field semantics.
- Actual protected VM/deployed SHA, backed-up original WAL/SQLite receipts,
  watchdog, restart/alerts and independently verified current DEMO identity.
- Full broker-wide fill/cancel/manual trade, funding, fee and realized account
  P&L reconciliation. The previous saved BTC scorecards remain provisional.
- Fresh broker-backed wallet risk assessment and separate explicit operator
  authorization for **one supervised BTCUSD DEMO trial**, with a human
  responder, full entry/SL/TP checks, emergency closeout plan and final
  broker-confirmed flatness. GPT-6 may choose WAIT. No unattended or
  real-money execution follows automatically.
- Gold has a separate consumed one-shot commissioning lock; nothing in this
  command can reset or bypass it.

The CLI never issues a trade, invokes any AI model, changes leverage,
modifies SQLite, creates lock files, enables dashboard FIRE or restarts
services. Exit 0 means *only* the limited read-only checks were consistent;
exit 2 means a required read-only check was blocked. See the authoritative
release checklist in GitHub issue #7.
