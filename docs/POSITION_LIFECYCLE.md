# Position lifecycle observation

Each demo worker polls broker margined positions, active orders, recent fills and
journaled entry orders before scanning. All lifecycle calls are read-only.
Exchange observations are saved in the per-market orders SQLite journal:
lifecycle_snapshots, observed_fills (deduplicated by exchange fill ID), and
observed_orders (latest known state by client ID).

- Positions report exchange margin, entry, mark, liquidation and unrealized P&L
  when supplied. Missing fields remain missing.
- Partial and terminal entry states are distinguished from acknowledgement.
- Bracket evidence means opposite-side stop and take-profit legs were observed
  in active orders. It does NOT confirm size coverage, exact intended prices,
  or linkage to a particular AI order. Missing data is not a flat position.
- Fill metadata preserves exchange-reported realized P&L and cashflow when
  present. These can be cumulative per position and must not be summed per fill.
  A flat-after-fill marker does not establish AI entry-level trade attribution.
- Each history refresh reads at most five pages of 50 rows; a truncated window
  is flagged. Full history backfill, exact close attribution, win-rate and
  capital-budget reconciliation remain pending. Order polling is capped at
  25 nonterminal entries per cycle; heavy backlog may delay older records.
- No automatic bracket repair, forced closing, new admission policy, or
  deployment is introduced. Live testnet contract behavior remains unverified.

API reference: https://docs.delta.exchange/ (India REST API).
