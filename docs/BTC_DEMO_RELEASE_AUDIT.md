# One-command BTC India DEMO blocker audit (read-only)

This operator launcher aggregates four existing fail-closed diagnostics. It
makes **no order mutations**, broker leverage edits, local ledger changes,
AI requests, firewall changes, daemon restarts, or trading configuration
changes to active services. It is NOT a release action.

Run on the **original, already-authorized VM** using its existing trusted
data directory and DEMO credentials, only after code review/merge and a
**separately reviewed, position-safe VM source deployment**. Keep both FIRE
controls disabled and an existing protective watchdog running. GitHub-hosted
runners were confirmed rejected as `SOURCE_IP_NOT_WHITELISTED`; do not add
ephemeral GitHub IPs to the trading key whitelist.

Do **not** use `git pull`, `git switch`, or restart any service as part of
the diagnostic. A working-tree update while an active protective watchdog is
using the checkout can impair protection. Inspect the VM's current source
version without changing it:

```bash
cd ~/Tradebot2.0 || exit 1
git rev-parse HEAD
git status --porcelain --untracked-files=all -- src/tradebot ops
```

If the VM checkout is older than the approved source, stop: arrange a
controlled deployment only after independently verified account flatness,
SQLite/WAL backups, independent risk review, and protection continuity. Once
the reviewed version is **already deployed**, execute the GET-only audit from
the approved VM console (never paste its keys or complete credential file):

```bash
cd ~/Tradebot2.0 || exit 1
umask 077
set +x
set -a
source "$HOME/.config/tradebot2/keys.env"
set +a
bash ops/run_btc_demo_release_audit.sh b7f242b10c584d6eacc831f9f713eaf8 "$PWD/data"
unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET
```

The launcher inspects its own Git ancestry and executable-source integrity
without modifying the repository. It fails closed on an outdated checkout,
modified source, missing original data, missing virtualenv or absent DEMO
credentials. The 32-character FIRE ID is used internally but redacted from
the script's initial progress message.

The launcher sequentially checks (1) current DEMO signed identity
authentication **from the VM's existing approved network**; (2) authenticated
broker leverage, isolated margin, all-product positions and orders;
(3) existing immutable equity observations, watchdog heartbeats and actual
daily/weekly UTC opening checkpoints; (4) BTC/Gold original archive
gaps/quarantines and independent BTC spot context; (5) the **exact selected
BTC FIRE ID's** original signed fill/wallet postings with a bounded
seven-day-from-origin API window; (6) combined VM services, current signed
wallet loss-budget assessment, two broker flatness samples and historical
bracket evidence.

Passing the 401 auth probe from the approved VM does not prove the other
checks pass. A selected historical FIRE may be eligible for diagnostic
inspection for up to 60 days but cannot be treated as reconciled if its
wallet postings lack independently verified ownership or funding evidence.

Each check has its own sanitized output and `CHECK_STATUS`. Failures do
not prevent the remaining read-only checks running. Even if all checks pass,
the audit intentionally exits **2** and always prints
`TRADING_ENABLED: false`. This prevents a shell or scheduler from
misinterpreting a diagnostic exit code as trading release. The underlying
`demo_release_evidence` report also says it is nonauthorizing.

**Important limitations:**
- The first two UTC equity opening windows must have actually been captured.
  Historical checkpoints are never invented, altered, or backfilled.
- M09 read-only in-memory analysis is not an immutable verified financial
  report. Delayed unreferenced cashflow/fee postings may remain unresolved.
- Existing BTC monthly candle extremes and Gold historical quality require
  separate independent review; this launcher does not release quarantines.
- Historic order fields do not prove that stop-loss and take-profit remained
  live continuously; a supervised lifecycle and independent recovery test
  must separately prove protective behavior.
- Order history screenshots and CSVs are not substitute evidence for signed
  broker wallet, fill and funding records.
- No retrospective audit proves future trading performance or safety.
- Gold's consumed one-shot commissioning lock is not changed or reset.

**Do not post** private keys, env file contents, full wallet transactions,
signed headers, account identifiers or balances. Share only the script's
sanitized diagnostic summaries. If blocked, investigate the specific reason
without weakening a gate, switching to a production API host, changing
leverage, or enabling unattended execution.
