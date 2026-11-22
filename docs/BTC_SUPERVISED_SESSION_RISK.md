# BTC supervised DEMO session equity policy — foundation, not activation

## Purpose
The operator wants to conduct **one supervised BTCUSD demo test** without
waiting for a missed weekly UTC opening to become available. The normal
unattended/manual FIRE trading controller has three authenticated equity
checks requiring genuine daily/weekly opening receipts. **Those remain
unchanged**. Neither the original historical Monday equity nor broker
data may be backfilled or fabricated.

This source-only increment provides a **read-only session baseline candidate**
and a pure, separately testable short-session loss policy. It does not create
session state, enable the dashboard, submit or cancel orders, modify the
account, write to the existing equity ledger, restart a watchdog or
implement a new execution route. It does not satisfy the remaining signed
account-margin, BTC archive integrity, complete financial accounting, or
protective-order commissioning gates.

## Session proposal policy
- Delta India DEMO BTCUSD only; at most one contract, one attempt.
- Fifteen minutes maximum between genuinely observed opening and last check.
- Fresh authenticated-HTTPS wallet read at proposal time; check matching
  transport receipt and client clock, not an unsigned manually typed equity.
- Preserve and validate the entire existing immutable equity history and
  its original high watermark before accepting a candidate.
- Genuine currently verified **daily** opening, freshest stored transport
  receipt, and healthy watchdog and collector are mandatory.
- A missing **weekly** checkpoint is the only existing standard health
  blocker condition permitted for **this nonauthorizing proposal**. No
  weekly record is fabricated or marked verified.
- Prospective session risk: 0.5% maximum loss from session start;
  8% maximum drawdown against validated historical highest equity; fail
  closed on an unexplained >2% account equity increase, missing receipts,
  clock/age ambiguity or elapsed session over 15 minutes.
- Existing independent per-trade `assess_fire_plan` (0.25% estimated
  risk including fees/slippage and one-contract cap), broker account-wide
  flatness and isolated-mode proof, trustworthy BTC archive, bracket
  confirmation and incident watchdog **cannot be removed** from any
  future supervised execution path.

The session risk policy only computes an analysis outcome.
`within_limits_review_only` **never** means order authorization.

## Operator read-only baseline candidate on reviewed staged source
Run on the existing approved VM after staging merged source in the separate
worktree. No API key is printed, and no broker POST is possible.

    set +x
    set -a
    source "$HOME/.config/tradebot2/keys.env"
    set +a
    PYTHONPATH="$HOME/Tradebot2.0-release-stage/src" \
      PYTHONDONTWRITEBYTECODE=1 \
      "$HOME/Tradebot2.0/.venv/bin/python" \
      -m tradebot.btc_supervised_session \
      --data-dir "$HOME/Tradebot2.0/data" || test "$?" -eq 2

This always exits 2 and prints boolean/categorical readiness fields only,
never amounts, personal account identifiers or raw wallet responses. It
cannot authorize trading or create a persistent session.

## Required next engineering increment
Build a **distinct supervised one-attempt controller** with:
1. Real durable one-attempt/one-session reservation shared with both FIRE
   products, plus a 15-minute monotonic and UTC expiry.
2. Independently rechecked authenticated session equity and preserved peak
   at baseline, immediately before any POST, and during an active position;
   no undefined historical-account realized P&L substituted for equity.
3. Original broker account-wide flatness and signed isolated-mode
   evidence; reject the observed Demo Main identity ambiguity unless
   authoritative signed verification becomes available.
4. Verified BTC history or an independently validated, expressly specified
   bounded data lookback policy, never deleting/ignoring suspicious prints.
5. Existing GPT-6-only proposal, risk governor, durable order intent,
   exchange-side SL/TP, independent watchdog, emergency closeout and fresh
   signed broker outcome.
6. Explicit local operator approval and independent final review. Do not
   change active dashboard flags or restart active services until those
   gates are implemented, reviewed and passed.

This operator-facing foundation does **not** authorize a trial today.
