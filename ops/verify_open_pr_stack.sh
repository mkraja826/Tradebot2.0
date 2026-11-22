#!/usr/bin/env bash
# Synthetic integration-only validation for the seven review-pending DEMO PRs.
# Git-only temporary branch; no merging to main, broker calls, VM deployment,
# financial ledger reads, paid AI, real accounts or trade authorization.
set -euo pipefail
set +x
umask 077

EXPECTED_BASE="521dcfc9374badd54c32069924e1c2b263fe0434"
PR_NUMBERS=(27 28 29 30 31 32 33)
PR_SHAS=(
  "2623799a88d08d8c6a9949e3cef45fd59463e32e"
  "7f73127ead7cd7b70e66c9e7ca12b6f3a2a7fb22"
  "439c6409b5c51b1bae5645b86d142e7158fbe8dd"
  "62c4c4c69ba2c5bac74ea0c04ce45b7fa320ab1a"
  "b23f4348a73530f7a45ad7a2f899c4197265ef28"
  "73169fdc949d372f35031b29bbb2aee8e2d91548"
  "6be064f6c5eed5b16137cd0d5732e454a1a8c5f3"
)

if [[ -n "$(git status --porcelain)" ]]; then
  printf 'BLOCKED: working tree not clean\n' >&2
  exit 2
fi
if [[ "$(git rev-parse --show-toplevel)" != "$(pwd -P)" ]]; then
  printf 'BLOCKED: run only from repository root\n' >&2
  exit 2
fi
for key in DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET OPENAI_API_KEY TB_API_KEY; do
  if [[ -n "${!key:-}" ]]; then
    printf 'BLOCKED: external account or AI credentials loaded in CI environment\n' >&2
    exit 2
  fi
done
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false

git fetch --no-tags origin main
ACTUAL_MAIN="$(git rev-parse refs/remotes/origin/main)"
if [[ "$ACTUAL_MAIN" != "$EXPECTED_BASE" ]]; then
  printf 'BLOCKED: main moved; review and update pinned integration manifest\n' >&2
  exit 2
fi
for i in "${!PR_NUMBERS[@]}"; do
  number="${PR_NUMBERS[$i]}"
  git fetch --no-tags origin "refs/pull/$number/head:refs/remotes/origin/pr-stack-$number"
  observed="$(git rev-parse "refs/remotes/origin/pr-stack-$number")"
  if [[ "$observed" != "${PR_SHAS[$i]}" ]]; then
    printf 'BLOCKED: PR #%s head changed; re-review and pin new SHA\n' "$number" >&2
    exit 2
  fi
done

git config user.name "read-only-integration-ci"
git config user.email "read-only-integration-ci@users.noreply.github.com"
git switch --detach "$EXPECTED_BASE"
git switch -c temporary-pr-stack-check

resolve_reviewed_test_collision() {
  local number="$1"
  local conflicts
  conflicts="$(git diff --name-only --diff-filter=U)"
  if [[ "$conflicts" != "tests/test_btc_readonly_release_audit.py" ]]; then
    printf 'BLOCKED: unexpected conflict files in PR #%s: %s\n' "$number" "$conflicts" >&2
    return 1
  fi
  # Only explicit known additive test collisions are allowed. Validate the
  # full incoming stage against the reviewed base before writing a union;
  # never use git -X ours, -X theirs, or a generic conflict-marker deletion.
  python - "$number" <<'PY'
import subprocess
import sys
from pathlib import Path

pr = int(sys.argv[1])
path = "tests/test_btc_readonly_release_audit.py"
def stage(n):
    return subprocess.check_output(["git", "show", f":{n}:{path}"], text=True)

base, ours, theirs = stage(1), stage(2), stage(3)
needle = '            "tradebot.fire_reconciliation_phase_probe",'
if ours.count(needle) != 1 or base.count(needle) != 1:
    raise SystemExit("BLOCKED: unknown audit test context")

if pr == 29:
    extra = '            "tradebot.candle_extreme_crosscheck",\n'
    expected = base.replace(needle, extra + needle)
    if (theirs != expected or extra in ours or
            '            "tradebot.candle_anomaly_inventory",' not in ours):
        raise SystemExit("BLOCKED: unreviewed PR29 audit-test collision")
    result = ours.replace(needle, extra + needle)
elif pr == 31:
    old = '            "tradebot.equity_checkpoint_health",'
    new = '            "tradebot.equity_monitor",'
    oldcheck = '        self.assertIn("TRADING_ENABLED: false", text)'
    added = ('        self.assertIn("risk_health(", text)\n'
             '        self.assertIn("watchdog", text)\n'
             '        self.assertIn("equity_collector", text)\n')
    expected = base.replace(old, new).replace(oldcheck, added + oldcheck)
    if (theirs != expected or ours.count(old) != 1 or
            ours.count(oldcheck) != 1
            or '            "tradebot.candle_anomaly_inventory",' not in ours
            or '            "tradebot.candle_extreme_crosscheck",' not in ours):
        raise SystemExit("BLOCKED: unreviewed PR31 audit-test collision")
    result = ours.replace(old, new).replace(oldcheck, added + oldcheck)
else:
    raise SystemExit("BLOCKED: no approved conflict resolution for this PR")

if "<<<<<<<" in result or "=======" in result or ">>>>>>>" in result:
    raise SystemExit("BLOCKED: merge markers remain")
Path(path).write_text(result, encoding="utf-8")
PY
  git add tests/test_btc_readonly_release_audit.py
  if git diff --name-only --diff-filter=U | grep -q .; then
    printf 'BLOCKED: unresolved paths remain after narrow conflict repair\n' >&2
    return 1
  fi
  git commit -m "CI-only reviewed additive audit test collision PR #$number"
}

for i in "${!PR_NUMBERS[@]}"; do
  number="${PR_NUMBERS[$i]}"
  sha="${PR_SHAS[$i]}"
  printf '\n=== Integrating PR #%s into ephemeral CI branch ===\n' "$number"
  if ! git merge --no-ff --no-edit -m "CI-only merge PR #$number" "$sha"; then
    printf '\nFound integration conflict at PR #%s; applying audited narrow rule if available\n' "$number" >&2
    if ! resolve_reviewed_test_collision "$number"; then
      printf 'BLOCKED: conflict cannot be safely resolved; no main changes made\n' >&2
      exit 3
    fi
  fi
done

printf '\n=== Combined-source Python test suite ===\n'
python -m pip install -e ".[plugin]"
python -m unittest discover -s tests -v
printf '\n=== Optimized Python risk and commissioning checks ===\n'
python -O -m unittest discover -s tests -p 'test_fire*commission*.py' -v
python -O -m unittest discover -s tests -p 'test_commissioning*.py' -v
printf '\n=== Shell and dashboard syntax ===\n'
bash -n ops/run_btc_demo_release_audit.sh ops/run_fire_watchdog.sh
node --check src/tradebot/dashboard_static/app.js
printf '\nCOMBINED_SOURCE_TESTS_PASS: true\n'
printf 'INDEPENDENT_REVIEW_COMPLETE: false\n'
printf 'VM_DEPLOYMENT_COMPLETE: false\n'
printf 'BROKER_FINANCIAL_RECONCILIATION_COMPLETE: false\n'
printf 'TRADING_ENABLED: false\n'
