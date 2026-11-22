# BTC one-attempt supervised DEMO FIRE (source-only commissioning)

## What is new
The preexisting dashboard FIRE endpoint stays explicitly disabled, and its
normal six-period history and genuine UTC day/week equity admission do not
change. The independent existing watchdog, parent+attached broker-side bracket
execution, durable entry intents, single-account portfolio reservation and
cross-product exposure checks are **reused**, not replaced.

A separate `SupervisedBTCController` can be invoked by a local **one-shot**
operator command only after a GET-only preflight and a typed confirmation.
It uses a first authenticated demo-wallet baseline with 15-minute expiry,
three authenticated equity rechecks (before model, before leverage change and
before order), retained original equity high watermark, original genuine daily
opening, and healthy existing services. The missed historical weekly opening
is never backfilled or relabeled verified. It uses a strictly validated
contiguous *last 24h* BTC DEMO candle context rather than supplying suspicious
month-derived highs/lows to GPT-6. A separate GPT-6 instruction describes
the limited scope and explicitly permits WAIT.

### Run read-only preflight on approved VM *after reviewed staging*
Do not run an execute flag while the original signed Main-account isolated
mode is unverified. This command is read-only, may perform authenticated
broker GETs, but has **no POST and no AI spending**. It uses original VM
`~/Tradebot2.0/data` but reviewed staged code:

```bash
set +x
set -a
source "$HOME/.config/tradebot2/keys.env"
set +a
PYTHONPATH="$HOME/Tradebot2.0-release-stage/src" \
PYTHONDONTWRITEBYTECODE=1 \
"$HOME/Tradebot2.0/.venv/bin/python" \
-m tradebot.fire_btc_supervised_commission \
--data-dir "$HOME/Tradebot2.0/data"
```

No request in ChatGPT, UI/dashboard setting or GitHub merge itself
authorizes an order. Treat `can_request_operator_approval=false` as a
real block, not a prompt to edit the lock or weaken policy.

### Operator-only execution contract (do NOT use until cleared)
Only after all current broker checks and independent commissioning review pass,
a local interactive terminal can **individually** approve a one-attempt DEMO
action using `--execute-one-btc-demo` and typing the exact approval phrase
`EXECUTE ONE BTC DEMO FIRE`. This consumes a durable, exclusive marker
`btc-demo-supervised-attempt.lock` *before* model/network activity, including
a GPT-6 WAIT. No automated repeat/retry; do not manually remove the marker
after ambiguity. The specific original `fire-ops.sqlite` is used so the
independent watchdog sees the same request and bracket receipts.

### Release prerequisites that this PR does NOT waive
- The original Delta India DEMO Main account has NOT produced a unique,
  account-scoped authenticated isolated-margin mode through the known
  signed readbacks. The current preflight fails closed. Get genuine evidence
  from Delta or a supported, independently verifiable DEMO identity.
- The short-history context is an **explicitly separate strategy input
  policy**, not proof that old BTC monthly anomalies are false. Monthly
  anomalies remain in the original archive. Same-provider 24h candles are
  locally checked but not an independent BTC perpetual trade-print proof.
  Treat this as a supervised DEMO measurement-only strategy; require separate
  signoff for use, and never use it to release autonomous/live trading.
- Original historical wallet commission/cashflow reconciliation remains
  unresolved. This pilot measures current signed equity and enforces
  account-wide flatness but does not invent net-realized-PnL proof.
- Watchdog/exits must be verified operationally before requesting an order,
  and independent incident-alert signoff remains necessary for rollout.
- Active VM source and services must NOT be overwritten or restarted
  outside a separate backup/recovery/protective deployment review.

This PR is an execution **implementation** with fail-closed runtime gates,
not evidence that a real order can currently be submitted.
