# One-command BTC India DEMO blocker audit (read-only)

This operator launcher aggregates four existing fail-closed diagnostics. It
makes **no order mutations**, broker leverage edits, local ledger changes,
AI requests, firewall changes, daemon restarts, or trading configuration
changes to active services. It is NOT a release action.

Run on the *already configured* VM, using the original trusted data directory,
only after code review/merge and verifying local source is at the expected
commit. Keep both FIRE controls disabled and the watchdog running.

```bash
cd ~/Tradebot2.0 || exit 1
git switch main && git pull --ff-only
export PYTHONPATH="$PWD/src"
set -a
source "$HOME/.config/tradebot2/keys.env"
set +a
bash ops/run_btc_demo_release_audit.sh b7f242b10c584d6eacc831f9f713eaf8 "$PWD/data"
```

The launcher sequentially checks (1) authenticated DEMO leverage and
isolated margin compatibility for BTC and Gold; (2) existing immutable
equity evidence and real daily/weekly UTC checkpoints; (3) selected
BTC fill/wallet posting attribution; (4) combined current VM service,
FIRE disabled, account-wide flatness and historical protective bracket
observations.

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
