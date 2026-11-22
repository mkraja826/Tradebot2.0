
## One-pass audit from the separate reviewed VM staging worktree

The protected VM has an existing live source directory and a separate
reviewed detached Git worktree. **Do not** modify/restart the live watchdog
or execute an in-place `git pull`. When the staged source has been updated
separately by an operator from the merged, green `main`, the read-only
release audit can use the existing live Python virtualenv explicitly:

```bash
ROOT="$HOME/Tradebot2.0"
STAGE="$HOME/Tradebot2.0-release-stage"
# Read-only review of the detached source revision and tree:
git -C "$STAGE" rev-parse HEAD
git -C "$STAGE" status --porcelain --untracked-files=all -- src/tradebot ops
(
  set +x
  set -a
  . "$HOME/.config/tradebot2/keys.env"
  set +a
  TRADEBOT_AUDIT_PYTHON="$ROOT/.venv/bin/python" \
    bash "$STAGE/ops/run_btc_demo_release_audit.sh" \
    b7f242b10c584d6eacc831f9f713eaf8 "$ROOT/data"
)
```

**Free off-host alert alternative (source-only audit correction):** the
generic HTTPS incident/dead-man webhook adapter is optional. Its unconfigured
state must not be conflated with the separate existing free Telegram incident
relay and Healthchecks.io missing-ping monitor. The audit now checks both free
channels' private 0600 owner-owned config, active local service/timer and
respective `--check` preflight without sending anything. A successful local
preflight reports `LOCAL_READY_REMOTE_DELIVERY_UNVERIFIED`, **not**
commissioning or evidence that a phone was notified. The operator must
independently verify real Telegram event acknowledgement and a genuine
Healthchecks missed-ping notification, while keeping the watchdog running.
If either required free channel is missing or unhealthy, the audit still
reports a blocker. No credentials or private check-in URLs are printed.

The combined audit now continues through **all** independent, read-only
checks even when isolated margin, financial reconciliation or missing
source records cause one stage to fail. It collects in one pass:
signed DEMO identity, signed full-account exposure independent of the
empty subaccount list, isolated margin/leverage, signed opening equity
and heartbeat integrity, historical BTC/Gold candle gaps, off-host
alert configuration (no outbound network), read-only journal permissions,
the exact original M09 fill+wallet financial evidence and structural
reference matching, combined host/receipt evidence and public source
context for suspicious BTC extremes.

The script **always exits nonzero and prints `TRADING_ENABLED: false`**
even when its diagnostics are consistent. It does not write/read provider
secrets outside the currently loaded environment, create a missing
reconciliation database, change journal permissions, call paid models,
install/restart units, place orders, mutate margin/leverage, or release
quarantined market bars. Off-host configuration check is not actual
verified delivery; BTC spot/mark context is not a perpetual trade print.

If a check is blocked, gather its fixed sanitized reason and continue
resolving it independently, without restoring old code or bypassing gates.

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
