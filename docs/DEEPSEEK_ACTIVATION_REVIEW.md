# DeepSeek position-management activation review
Status: staged only. No service changes, restart, merge or activation are authorized by this document.

## Evidence already collected
- BTC synthetic profitable short: 10 to 5 contracts, valid proposal, 6855 ms (run 45721423980).
- Gold synthetic losing long: 10 to 7 contracts, valid proposal, 4517 ms (run 45721808724).
- These are provider contract tests, not exchange fills or model-quality backtests.
- Earlier manual BTC stop and partial reduction evidence is recorded in MANAGEMENT_EXECUTOR.md. That is not proof of current automated executor or Gold compatibility. The newer executor supports TP-only amendments, but TARGET_AMENDMENT_PREVIEW.md documents offline compatibility only.
- The shipped service unit currently omits --manage-demo. Actual VM overrides and active model assignments must be checked.

## Read-only VM inspection (no secrets in output)
Run on the existing VM. These commands do not change a service or submit an order.
```sh
systemctl is-active recover-demo.service
systemctl show recover-demo.service -p MainPID -p FragmentPath -p DropInPaths
systemctl list-timers --all --no-pager | grep -i kimi || true
systemctl list-units --all --type=service --no-pager | grep -i kimi || true
sudo python3 - <<'PY'
import subprocess
from pathlib import Path
pid = int(subprocess.check_output(["systemctl","show","recover-demo.service","-p","MainPID","--value"],text=True).strip())
if pid <= 0:
    raise SystemExit("Recover service has no active PID")
env = dict(item.split(b"=",1) for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in item)
for k in ("RECOVER_BTC_MODEL","RECOVER_GOLD_MODEL","RECOVER_MANAGEMENT_MODEL"):
    v=env.get(k.encode())
    print(k, v.decode(errors="replace") if v else "(unset)")
args=Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
print("manage_demo_enabled", b"--manage-demo" in args)
print("learning_journal_enabled", any(a==b"--learning-journal" or a.startswith(b"--learning-journal=") for a in args))
PY
```
Do not print the entire environment or credentials. The model values are configuration identifiers, not secrets. A timer listing does not exclude a separate scheduler; inspect any identified Kimi unit before disabling it. Preserve existing review and learning databases.

## Before activation
1. Confirm actual BTC and Gold entry models, existing manager mode and active scheduler identity. Do not change entry models implicitly.
2. Confirm complete offline CI for the final candidate. Keep paid smoke workflow non-repeating.
3. Validate TP-only and SL-only amendments, partial reduction and full close in a dedicated isolated demo test account without an active strategy worker. Do not use either occupied trading account. Verify reduce-only behavior, bracket quantities, unchanged opposite trigger, and fill reconciliation. If no separate account exists, record the blocker; do not claim validation.
4. Review the synchronous manager request latency limitation; a request can delay its own market worker. Do not claim independent asynchronous management.
5. Obtain explicit activation approval. Use existing deployment and rollback process; confirm current positions, existing brackets and service health before and after. Keep historical learning opt-in until its prospective comparison is complete.
6. Suspend only the identified Kimi paid scheduler following approval; do not delete historical evidence or stop the trading engine. No Opus service is introduced.

## Rollback design
Revert to the prior verified release/configuration using the established deployment process and verify exchange positions and orders. Never replay an ambiguous mutation. No changes to leverage, capital allocation, entry signals or broker accounts are part of this review.
