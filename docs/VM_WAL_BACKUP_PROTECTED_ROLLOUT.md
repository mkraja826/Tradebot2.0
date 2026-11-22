# Original VM — private WAL-aware backups and no-restart deployment gate

## What this closes and what it does not

This upgrade replaces a risky `cp data/*.sqlite` pattern with Python's
SQLite **online backup API**. A database running in WAL mode can have
committed trades, risk events, wallet history or protective-alert information
in its active `-wal` file. Copying only the `.sqlite` file might silently
lose those transactions. **Do not manually copy/delete a live WAL or SHM.**

The new `tradebot.vm_backup_snapshot` tool reads each original DB in
SQLite read-only mode, makes an internally consistent, standalone online
backup, and validates the resulting database with full
`PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
It includes **all** top-level `*.sqlite` and `*.jsonl` files in the
original `data/` directory, including the required:

- `fire-ops.sqlite` — BTC receipts and order/entry intents
- `fire-xaut.sqlite` — Gold receipts and emergency-lock continuity
- `fire-reconciliation.sqlite` — broker evidence/reports
- `fire-equity-risk.sqlite` — immutable risk/equity history
- `fire-monitoring.sqlite` — watchdog health, incident outbox and cursors
- `delta-demo-candles.sqlite` — original and quarantined market history

Existing append-only `*.jsonl` journals are also copied only when they
remain unchanged during the operation. Missing/linked/too-permissive/corrupt
files are **blockers**, never replaced with blank databases or synthetic
receipts. The tool cannot mutate the source files, change leverage, call paid
AI, place/cancel broker orders or modify systemd services.

## Separate private destination (on the original approved VM)

Create an operator-owned, mode-0700 directory **outside** the live `data/`
tree. The backup holds sensitive order/financial evidence. Do not upload
to ChatGPT/GitHub, put under a public web root, or print its contents.

```bash
cd ~/Tradebot2.0 || exit 1
umask 077
mkdir -p "$HOME/.config/tradebot2/private-backups"
chmod 700 "$HOME/.config/tradebot2/private-backups"
export PYTHONPATH="$PWD/src"

# Default: read-only filesystem preflight, absolutely NO backup writes.
.venv/bin/python -m tradebot.vm_backup_snapshot \
  --data-dir "$PWD/data" \
  --backup-root "$HOME/.config/tradebot2/private-backups"

# Explicit operator action only: back up the existing databases even when
# current broker flatness has not yet been established. This is preservation,
# NOT permission to deploy a new watchdog or dashboard.
.venv/bin/python -m tradebot.vm_backup_snapshot \
  --data-dir "$PWD/data" \
  --backup-root "$HOME/.config/tradebot2/private-backups" \
  --create-backup
```

The final snapshot folder and manifest are private (0700 / 0600).
`manifest.json` contains filenames, byte lengths, SHA-256 hashes, a
per-database integrity result and explicit
`cross_database_atomic=false`, `deployment_authorized=false`.
Backup completion is **not** proof all six SQLite databases represent one
single point in time: independent database transactions can occur between
the individual online backups. The source VM's original live files,
WAL/SHM and service processes are never checkpointed, deleted or replaced.

If the command reports `incomplete_private_backup_requires_review`, a
private `.incomplete-snapshot-...` directory may remain for inspection.
Do **not** use or rename it as a completed backup. Only directories named
`snapshot-...` with a verified `manifest.json` can be considered
completed snapshots; confirm their copies are on persistent storage and
subject to an approved restore test before any production change.

## Stronger deployment-candidate evidence (GETs only)

Once an approved key is loaded **on the VM with a whitelisted egress IP**,
an operator may request a fresh two-sweep signed account/ledger check as a
**precondition to a new backup**. This mode fails closed before creating the
snapshot if the signed inventory is unavailable, an unrelated market has an
open position/order, a local entry intent is unresolved, isolated margin
cannot be proved, the broker samples disagree, or the samples are not at
least 11 seconds apart.

```bash
set +x
set -a
source "$HOME/.config/tradebot2/keys.env"
set +a
.venv/bin/python -m tradebot.vm_backup_snapshot \
  --data-dir "$PWD/data" \
  --backup-root "$HOME/.config/tradebot2/private-backups" \
  --require-two-signed-flat-sweeps --create-backup
unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET
```

A standalone preservation-only backup can still be appropriate if the
broker is NOT yet verifiably flat; its report never asserts flatness or
deployment readiness. Do not erase WAL, force-close an unknown position,
waive incomplete wallet/funding history or change the API key whitelist to
make a stronger gate pass.

## Deployment remains separately blocked

Even a passing signed backup mode only proves **bounded, historical flat
samples plus private backup integrity at that time**, not ongoing flatness.
Before any unit promotion/restart, an independent operator must again
verify account-wide flatness/zero pending orders, actual FIRE off, no
unprotected positions, original runtime/watchdog heartbeat, system clock,
SQLite restore viability and off-host receiver acknowledgement. Use the
separate source-reviewed staged-unit candidate, never the old unconditional
watchdog installer. Record independent approval and protect the previously
running watchdog throughout the change window.

The former `fire_release_gate` had two bugs: it still queried the
deprecated authenticated `/v2/profile`, and it assumed a sleep callback
really waited 11 seconds. Both are now corrected: signed current-account
margin-mode ID matching is used, a real monotonic elapsed interval is
required, and the gate no longer claims service restart authorization merely
because broker snapshots appear flat.

Other independent blocking evidence remains: M09 wallet cashflow/commission
attribution, BTC suspicious archive extrema, Gold missing candles, genuine
daily/weekly equity checkpoints, actual alert delivery and final protected
BTC DEMO release sign-off. `TRADING_ENABLED` stays false.
