# Supervised BTC DEMO — operator-declared Main + Isolated margin

The owner selected **Delta India Demo / Main Account / Isolated** and agreed
to update the private declaration if their exchange settings change.

**Evidence classification:** `owner_declaration_not_broker`. This is
deliberately NOT broker verification and never reports
`signed_isolated_margin_verified=true` without actual broker evidence.

The BTC-only supervised commissioning preflight reads the existing
support-owned, private 0600 operator mode declaration. It is constrained to
the Delta India DEMO host and expires after 30 days unless renewed. A missing,
insecure, expired, wrong-market or contradictory declaration fails closed.

The separate `SupervisedBTCController` uses the owner-mode path on
**all three** account-exposure checks (before indicators, after the GPT plan,
and immediately before order intent). Each check still obtains authenticated
account-wide positions, all open orders, and live BTC/gold position data.
The signed broker equity receipts, 15-minute session loss limit, live
margin/leverage budget, GPT risk checks, public BTC spot-price sanity,
broker SL/TP reconciliation, liquidation clearance, watchdog, one-attempt
durable lock, and explicit terminal operator consent are unchanged.

The standard FIRE controller still requires signed broker isolated-margin
evidence, and gold/live exchanges cannot use the owner-declaration path.

This change **does not** authorize placing an order by itself. The read-only
commissioning preflight may return `can_request_operator_approval=true`.
Only an explicitly approved, separately controlled BTC demo attempt may
access the order-capable execution path; no order was submitted during
implementation, and dashboard FIRE remains disabled.

Historical financial reconciliation remains unresolved; this policy does
not label historical P&L or exchange margin mode independently verified.
