# One-time signed broker compatibility audit (GitHub Actions, DEMO only)

This job is deliberately separate from the original Google Cloud VM
deployment and never attempts to alter either trading market.

## Why this is useful

GitHub's existing Delta India DEMO credentials can read current account
configuration even when the VM's original financial and market-data SQLite
files are unavailable in ChatGPT. The job uses the audited
`tradebot.fire_leverage_probe` with `allow_orders=False`, **not** FIRE.

It runs on the first merge of
`.github/workflows/broker-readonly-preflight.yml` to `main`, and can be
repeated manually using `workflow_dispatch`. Later source merges do not
automatically repeat the signed account GET. GitHub Actions permissions are
`contents: read`; credentials are only injected into this one job.

## Verified scope

- Both market product identities are matched to signed Delta India DEMO
  account configuration, and chosen settings are integral 1×–20×.
- The account profile is **isolated margin**.
- The account's unfiltered positions and all-page open/pending orders are
  sampled: exposure in a market other than BTC/Gold is not overlooked.
- Independent BTC and Gold real-time position sizes are compared to the
  unfiltered signed margined positions.
- Missing/contradictory or incomplete evidence yields static blocker codes
  and an unsuccessful job. A failure does **not** attempt to change leverage,
  close an unrelated position, cancel orders or alter broker balances.
- Private keys, account IDs, order details and account balances are excluded
  from printed report fields.

## Evidence limitations

Even a green signed-GET result is a **single point-in-time** observation.
It is not the separate account-wide two-sweep inventory spanning at least
11 seconds, does not verify current Google Cloud VM instance provenance,
watchdog continuity, equity anchors, M09 wallet posting identity, price
history quality, external Telegram delivery or independent approval.

The maximum allowed leverage remains 20×; it is not a leverage recommendation.
The runner does not set `trade_authorized`, `safe_to_deploy`,
`safe_to_enable_fire` or any enabling environment variable. DEMO FIRE
remains off. Any required broker setting correction must be handled through
a separately reviewed manual procedure, not by this read-only job.

**Failure to access DEMO credentials** means this verification cannot be
completed from GitHub; do not substitute local fabricated test data for the
authenticated result or move to a production endpoint.
