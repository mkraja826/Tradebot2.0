# BTCUSD unattended Delta India DEMO — read-only diagnostics

This mode is intentionally independent from the general dashboard FIRE endpoint. It never supports live/production credentials or endpoints.

## Check blockers without AI spend or broker orders

```bash
cd ~/Tradebot2.0
set -a; source ~/.config/tradebot2/keys.env; set +a
PYTHONPATH=src .venv/bin/python -m tradebot.btc_autonomous_readiness --data-dir data
```

The report performs fresh **read-only** authenticated Delta DEMO preflight checks. It does not mutate broker settings, create entries, add audit receipts, call GPT-6, or arm the worker.

The existing `tradebot2-btc-autonomous-demo.service` is **not authorized** by this report. It retains its separate private owner arm file, daily trade budget, durable attempt journal, equity loss ceiling, signed account-wide flatness, model validation, exchange leverage/liquidation rechecks and attached broker protection.

### Known blockers (23 November 2026)

- `owner_autonomous_arm_missing`: owner-operated mode-0600 arm file does not exist. This is an intentional safety gate, not a software failure.
- `previous_fire_requires_operator_review`: latest historical BTC FIRE was `rejected_no_order` with `model_decision_failed`. Its no-order record must be reviewed before any independent unattended session. **Do not rewrite or delete that receipt.**
- One-shot supervised commission was already consumed. That irreversible one-shot marker is **not an unattended worker requirement** and must not be removed.
- GPT-6 model appears in the provider's catalogue and the configured credential is present in active services. This does not prove an actual paid model completion succeeds.
- A previous generic model failure cannot be assigned a precise cause retroactively. New model failures carry a bounded internal request/completion/validation stage to improve diagnostics without storing upstream messages.
- GPT-6 via Top Billing currently does not advertise structured output; do not set `response_format`. The new explicit `max_completion_tokens` cap limits credit consumption without assuming model returns valid JSON.

A report of `eligible_read_only_no_order` **never** authorizes a trade. The autonomous process itself checks fresh evidence again at execution time.

## Operator recovery

1. Diagnose model route (read-only catalogue), input format and bounded errors.
2. Inspect the exact last FIRE receipt: model failure, `orders_submitted=false`, no broker intent, current signed account-wide exposure flatness, and independent watchdog health.
3. Require explicit owner approval for any release from a model-error stop or unattended arming. Do not bypass manual review by directly editing a trade record.
4. Leave all order execution flags off until an authenticated DEMO-only end-to-end readiness review passes.

## Audited recovery of the exact historical no-order model failure

Read evidence without modifying anything:

```bash
cd ~/Tradebot2.0
PYTHONPATH=src .venv/bin/python -m tradebot.btc_auto_review --data-dir data
```

After reviewing the exact model-failure receipt, proving that its
`orders_submitted` value is false and there is **no durable `fire_entries`
intent**, and confirming fresh authenticated signed broker exposure is flat
with the independent protection services working, an authorized operator can
acknowledge that one record:

```bash
set -a; source ~/.config/tradebot2/keys.env; set +a
PYTHONPATH=src .venv/bin/python -m tradebot.btc_auto_review --data-dir data \
  --acknowledge \
  --approval 'REVIEW BTC DEMO MODEL FAILURE WITH NO ORDER'
```

The acknowledgement creates a private mode-0600 `data/btc-auto-reviewed-no-order.json`
marker containing the exact receipt identity and SHA-256 digest, without
rewriting or removing the original FIRE record. It rejects changed receipts,
any durable broker intent, unverified signed DEMO flatness, unknown failures
or mismatched marker permissions.

**This is a review of a proven historical no-order event, not a trade
authorization.** It does not create the separate autonomous arm file, touch
broker settings, restart services, or call GPT. A new failure is not
automatically reviewed. The worker continues to impose its normal halt latch,
daily and per-trade risk limits, and broker protection checks at execution time.
