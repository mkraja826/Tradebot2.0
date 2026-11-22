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
  "cf624b6a9c1f72e586d4663a36738dd9f9d3715e"
  "7f73127ead7cd7b70e66c9e7ca12b6f3a2a7fb22"
  "df8150d48593255cc903f3595c1172e555e749b4"
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

for i in "${!PR_NUMBERS[@]}"; do
  number="${PR_NUMBERS[$i]}"
  sha="${PR_SHAS[$i]}"
  printf '\n=== Integrating PR #%s into ephemeral CI branch ===\n' "$number"
  if ! git merge --no-ff --no-edit -m "CI-only merge PR #$number" "$sha"; then
    printf '\nBLOCKED: merge conflict after PR #%s; no main changes made\n' "$number" >&2
    git diff --name-only --diff-filter=U >&2
    exit 3
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
