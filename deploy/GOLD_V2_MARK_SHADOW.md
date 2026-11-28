# Mark hybrid shadow deployment checklist

This is a research-only deployment plan. It does not authorize installation,
stopping legacy Gold, restarting BTC, placing orders or enabling demo execution.

## Before installation
- Verify exact approved Git revision and passing isolated, full and browser CI.
- Verify service user, release directory, filesystem free space and ownership.
- Use a new versioned checkout under /opt/recover-gold-v2. Do not overwrite the
  existing engine or reuse its data directory.
- Inspect the real server topology and confirm dashboard reader permissions.
  The prepared unit uses recovertrading and mode 0700; a different dashboard
  user cannot read it without an explicitly scoped read-only export or ACL.
- No API key, secret, account selection or environment-file changes are needed
  for public research. Do not grant the research service trading credentials.
- Verify the mark cohort directory is distinct from the existing strict cohort.
- Install and start only recover-gold-v2-mark-hybrid.service after approval.
  Do not enable or restart the trading services.

## Observe after start
- Check status freshness, exact source, service PID and journal source binding.
- Verify quote observations arrive near the intended 10-second cadence and
  measure timestamp gaps, duplicate rates, API errors and disk growth.
- Verify reference evaluations every 5 minutes and diagnose expired signals.
  Macro collection is currently in the reference task and may cause expiry;
  network timing and available API quotas remain unverified on the VM.
- Validate the Gold dashboard separately. Existing dashboard unit arguments
  and permissions are not known; pass --mark-hybrid-dir if necessary.
  Dashboard code must be deployed independently and tested without BTC restart.
- Do not expect any trades, real fills or immediate profitable sample.
- Fix the training cutoff prospectively before holdout enrollment. Run
  gold_v2_mark_learning with --journal, --cutoff, --as-of and --publish-dir
  as the research owner when publishing a snapshot. No automatic promotion.

## Stop / rollback
Stop only the new research unit. Retain the SQLite journal and status
snapshots. Revert the independent dashboard release if required. Do not
alter existing orders, positions, live engine or legacy history.

## Unresolved execution requirements
Mark research is NOT wired to the demo executor. Research validation cannot
establish actual fills, stop coverage, sizing, order ownership or realized
costs. A separate approved runtime integration and exchange verification
would be required. The existing cutover checklist remains applicable.
