# Delta India DEMO — broker-only exposure diagnostic (read-only)

This is an **optional evidence-gathering utility** for the staged BTCUSD
supervised DEMO release. Its purpose is to independently check the authenticated
DEMO broker's account-wide *current* exposure when an older deployment lacks
`fire-reconciliation.sqlite` or still has historical records needing review.

**Not a release gate or permission to trade.** The strict
`tradebot.demo_release_evidence` and `tradebot.fire_broker_inventory` checks
continue to fail closed on incomplete local history, including a missing
financial reconciliation ledger. This diagnostic does not override them or
close any historical trade investigation, erase errors, modify the Gold
one-shot lock, or certify complete net P&L. No historical Gold investigation
is required to run it, although current account-wide Gold exposure is checked
as a mandatory BTC safety condition.

## Review and prerequisites

1. The branch is a **draft**, not deployed. Obtain independent code/risk review
   before using it with authenticated DEMO credentials or an active account.
2. On the operator-controlled VM, independently verify the exact checked-out
   commit, DEMO-only credentials, synchronized UTC clock, both FIRE
   execution switches disabled, watchdog active, and original evidence
   backups. Keep the original running VM untouched during source review.
3. Run from a separately reviewed staging Python environment, with the
   operator's existing protected **Delta India DEMO** read-only credentials.
   No production keys or endpoints. Do not paste credentials into chat or
   GitHub.

```bash
cd ~/Tradebot2.0-review
PYTHONPATH="$PWD/src" "$PWD/.venv/bin/python" -m tradebot.demo_broker_presence
```

The operator should run this command only after satisfying the prerequisites.
The module does not load credential files, so prepare its environment securely
using the operator's existing approved process; never copy keys into the
review branch, test fixtures, shell output, or public logs.

## Exact scope

- The broker is fixed to `DeltaDemo(allow_orders=False)`, with the normal
  signed authenticated **GET** request path.
- Two account-wide sweeps are separated by at least **11 measured monotonic
  seconds**, with bounded per-sweep duration and validated responses.
- Every sweep checks isolated margin profile, the unfiltered margined
  position list, **all** paginated open/pending orders across every product,
  and exact signed BTCUSD/XAUTUSD real-time position sizes. It rejects
  inconsistent margined vs real-time positions and changed broker state.
- Output contains only fixed sanitized booleans, counts and blocker codes.
  No account IDs, order IDs, wallet amounts, raw provider exceptions, API
  keys, or request bodies.
- It does **not** query local SQLite at all: no database creation, inserts,
  migration, backup, repair, or retroactive evidence synthesis.
- No GPT-6, DeepSeek or Kimi calls; no POST, DELETE, leverage change,
  dashboard toggles, service restarts, or commission-lock handling.

An exit code **0** means only
`two_flat_broker_snapshots_only_not_release_authority`. Even that output
always has `trade_authorized=false`, `safe_to_enable_fire=false`,
`ready_for_unattended_trading=false`, and
`local_reconciliation_complete=false`. No historical fill/funding/fee
coverage is established. The account can change after the observation.

An exit code **2** means incomplete credentials, broker reads, timing,
profile, open orders, positions, or source consistency. Do not alter or
relax checks to force success. Raw broker history may be investigated later
under independent authority; this feature deliberately does not do so.

## Still required for supervised BTC trial

Independently approved merged code and operational change; protected original
VM ledger and Gold lock; complete broker/local reconciliation; genuine
daily/weekly equity checkpoints with receipt provenance; fresh wallet risk
admission and 2% daily / 5% weekly / 8% observed-peak limits; checked broker
leverage and protective-order semantics; active watchdog/collector; off-machine
alerts; an explicit operator authorization for **one BTCUSD DEMO lifecycle**
with a human responder. No unattended or real-money trading is authorized.
