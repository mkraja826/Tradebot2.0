# Account-wide leverage and flatness — signed GET diagnostic hardening

## Scope of the defect

The original `fire_leverage_probe` read only filtered BTCUSD and XAUTUSD
positions/open orders. That is insufficient to establish account-wide
flatness: a separate perpetual or manually placed order can coexist while
both FIRE markets show zero contracts. Its previous `blockers=[]` status
could then be misread as broker readiness despite external account exposure.

## New read-only checks

The probe still reads the isolated-margin account profile and the individual
broker leverage settings for BTCUSD and XAUTUSD (selected 1×–20× maximum),
but now requires:
- both connected broker clients to be **read-only Delta India DEMO** before
  any account GET is attempted;
- matching signed product IDs in the leverage GET (missing ID fails closed)
  and integral 1×–20× settings;
- one extra unfiltered authenticated account snapshot using the existing
  `fire_broker_inventory._sample` implementation;
- complete account open/pending order pagination (including non-FIRE orders);
- unfiltered margined positions across all products, not just BTC/Gold;
- independent BTC and Gold filtered real-time positions, consistent with
  the unfiltered margined snapshot;
- explicit signed isolated-margin profile, matched product identities, and
  comparison with the prior market-filtered leverage-probe reads.

The probe reports only allowlisted counts/booleans and fixed blocker codes.
No account balances, API secrets, order IDs, broker response bodies, or
position details outside BTC/Gold are published.

## What it does NOT prove

One signed snapshot is **not** two independent flatness samples, and does not
prove flatness at a future point. The existing
`fire_broker_inventory.observe_broker_inventory` separately requires
two complete broker/account snapshots separated by at least 11 seconds,
plus preservation of the original local receipt/ledger state. Both checks
remain required in the full read-only pretrade audit. A later external
order can always change account exposure; the final execution controller
already rechecks account-wide flatness immediately before order intent.

The `safe_to_deploy`, `safe_to_enable_fire`, and `trade_authorized` flags
remain **false** for all probe outcomes. A `blockers=[]` diagnostic is not
an execution release. This does not alter the 20× maximum, trade sizing,
leverage mutation logic, loss limits, source historical repairs, protective
stops, funding reconciliation, or the VM process.

Do not use a broker response from a live Delta India API host or bypass
missing pagination metadata. Investigate every unverified/active exposure
using signed broker GETs; never automatically cancel unrelated manual orders
or close another person's position.
