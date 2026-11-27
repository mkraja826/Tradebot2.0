# Gold V2 clean-slate replacement

Base: recover/gold-volatility-trail (repository candidate, not verified deployed SHA).
Scope: XAUTUSD demo only. The new modules do not import legacy strategy signals.
BTC, exchange execution, account isolation, lifecycle, history and dashboard remain unchanged.

## Current alpha
- gold_v2_engine: closed 5m/15m/1h candles, independent EMA/ATR regime and three signal families.
- gold_v2_scan: public demo-only feed, converts candle open timestamps to close timestamps.
- gold_v2_replay: hypothetical next-bar entry outcomes, round-trip cost scenario, explicit gaps and ambiguous bars.

Run from repository root:
    python3 -m unittest discover -s tests -p 'test_gold_v2*.py' -v
    python3 -m recover_trading.gold_v2_scan --once

The second command makes public read-only network requests. No credentials or orders.
The replay is a per-candidate primitive, not a complete prospective ledger, broker fill simulator,
or validated performance result. ATR multipliers, cost, and horizon are research assumptions.
Extreme candle checks currently flag only the latest range; earlier anomalous bars need independent review.

## Before replacement
1. Add point-in-time macro context, sessions, independent reference and full data-quality checks.
2. Add durable opportunity journal and non-overlapping validation, with at least 1000 observed opportunities.
3. Add tested position and exit management, realistic fees/funding/spread, and account isolation tests.
4. Review exact deployed revision; wire V2 exclusively into XAUTUSD, retiring legacy Gold entry routing.
5. Verify no active Gold exposure or unresolved orders before switching ownership; keep rollback revision.
6. Run full regression suite, verify BTC unchanged, and separately authorize demo deployment.

No production account access. No running service changes in this branch.

## Unified evidence fusion
gold_v2_score.py annotates each candidate with two equally weighted evidence groups:
- Technical: majority sign of 5m, 15m and 1h EMA alignment.
- Macro: inverted broad dollar and real yield changes with provisional 0.2 percentage
  point and 5 basis point bands, respectively.
A group with missing data has unknown direction. Neutral is observed zero. Candidate
support index is a sum of known group alignments from -2 to +2, accompanied by
observed/expected group counts. It is NOT a calibrated probability, trade selector,
or validated strategy. Compare scores only with coverage disclosed.
CFTC positions, gold/silver ratio, gold basis, token prices, other macro series and
economic release metadata are context only; no unvalidated or duplicate votes.
Session labels are fixed UTC research windows, not official market hours.
No evidence packet dated differently from the decision cutoff is scored.
Next: durable point-in-time enrollment and non-overlapping validation, before
calibration or execution routing.

## Prospective validation (validation.1)
The SQLite journal records the first accepted observation per five-minute signal
boundary, including the complete evidence packet and model versions. Enrollment
requires a current observation, not retrospective history. Entry starts at the
strictly next five-minute boundary after enrollment. Outcomes use 12 subsequent
closed five-minute bars (one hour); all candidates in a window share that window.
Later candidate windows overlapping any enrolled window are recorded but excluded.
The non-overlapping window count is not a count of independent candidate trades,
and serial market dependence may remain. Cost scenarios: 5, 15, 30 round-trip bps.
Missing bars remain pending up to 24 hours after the horizon, then are excluded.
Ambiguous intrabar stop/target order is excluded, with counts reported. Resolution
is once-only; no retroactive revision or automatic weight adjustment.
Summary stratifies by engine/scoring version, family, side, evidence index,
coverage and cost. Target is 1,000 observed non-overlapping windows, not 1,000
correlated signals. This takes at least 1,000 hours of eligible horizon coverage,
and likely much longer. Results are hypothetical, not actual fees, funding,
broker fills or proof of profitability. No scheduled worker has been installed.
Run manually from an isolated checkout:
    python3 -m recover_trading.gold_v2_validate_cli --journal gold-v2.sqlite --fundamentals --public-feeds
    python3 -m recover_trading.gold_v2_validate_cli --journal gold-v2.sqlite --summary
The first command reads public demo feeds; the second is offline. Each invocation
is one cycle. No exchange order or live service modifications. Historical wick
quality, archive retention, out-of-sample validation and learning evaluation
remain pending; no claim of tested profitability.

## Advanced technical entries (alpha.3)
New pure-Python indicators: Wilder RSI14, ADX14, DI+/DI-, rolling 20-bar
typical-price VWAP (not session VWAP or tick VWAP), relative volume against
the preceding 20 bars' median, and confirmed two-bar fractal structure.
All are computed on closed candles; zero-volume VWAP is unavailable.
Four new symmetric entry families supplement the original three:
- Volume-confirmed breakout: 5m ADX >=25, directional DI dominance,
  15m/1h alignment, volume >=1.5x prior median, break >=0.15 ATR.
- VWAP trend reclaim: 15m/1h alignment, crossing rolling VWAP with
  relative volume >=1.
- Range RSI reversal: ADX <20, RSI re-entry through 30 or 70, price
  on the appropriate side of rolling VWAP.
- Structure continuation: confirmed rising/falling swing pairs, 15m/1h
  alignment, break of prior confirmed swing by >0.1 ATR.
These are candidate hypotheses, not selected trades. Existing scoring and
validation capture their family/version, with no change to broker routing.
Historical range quality now flags anomalous prior true ranges using a
rolling 40-bar median and an initial-history median. This is heuristic:
it cannot distinguish genuine volatility from corrupted candles, and is not
independent reference-price reconciliation. Thresholds and all strategy rules
are uncalibrated. The original ATR stop/target hypotheses remain unchanged.

## Position scaling (sizing.1, validation.2)
Compare four policies on identical opportunity windows: fixed, add winners,
reduce losers, and combined. Initial normalized quantity is one unit, with at
most five one-unit additions and one half-position reduction. Add thresholds
are favorable 0.5 ATR increments from original entry; reduction is triggered
by a 0.5 ATR adverse close. Recheck direction at the next bar open. Existing
bracket takes precedence; stop and target remain anchored to initial entry.
These are uncalibrated research assumptions, not recommended allocations.
Per-fill fees use half of the scenario round-trip bps times fill notional.
All results are normalized to original notional; higher exposure is not
risk-equivalent to fixed size. Peak quantity and a conservative bar-high
notional upper bound are reported. No leverage, margin, liquidation,
funding, actual balance, contract rounding or executable fill model.
Only validation.2 enrolled windows receive the new paired outcomes, preserving
older policy cohorts. Summary includes pairwise means and sample counts; an
unobserved outcome is not a paired sample. No broker or automatic deployment.

## Intelligent stop-loss (stop.1, validation.3)
Compare fixed, ATR trail, EMA9 trail, rolling three-bar structure trail and
hybrid policies on identical fixed-size windows with unchanged take profit.
Activation after favorable best close of 0.75 entry ATR; ATR uses Wilder
updates seeded from signal ATR, EMA9 from signal evidence, structure uses
three completed post-entry candles. The seed omits the intervening candle
between signal and simulated entry, so the indicators are approximations.
ATR distance 1.5 updated ATR, EMA buffer 0.25 ATR, structure buffer 0.1 ATR.
Hybrid selects the tightest eligible level and considers estimated cost-adjusted
entry after one ATR of favorable movement. Stops ratchet only toward or
through entry; never widen, and no retroactive same-bar application. Gaps
can realize worse prices; breakeven is not guaranteed. Ambiguous intrabar
ordering excluded and reported. All values are provisional hypotheses.
Only validation.3 enrollments receive stop comparisons; prior scaling cohorts
remain intact. Stops and resizing are separate experiments, not yet combined.
No broker writes, no live margin/liquidation model, no tested profitability.

## Intelligent take-profit (target.1, validation.4)
Five paired fixed-quantity, fixed-stop research policies: fixed target, partial
profit, trend extension, profit giveback exit, partial plus giveback. Partial
closes half of initial quantity at half of target distance. Extension occurs
once, by one entry ATR, before target hit, after 60% target-distance progress
and two favorable closes with a minimum current body of 0.25 ATR. Giveback
tracks favorable closes; after one ATR gain and 0.75 ATR giveback, it schedules
remaining exit at the next opening. Existing bracket orders take precedence.
Intrabar stop versus target order ambiguity is excluded. Partial target gaps
use conservative target references. Same-window fixed benchmark and all
variants use a flat scenario cost on initial notional (5/15/30 bps), not actual
per-fill fees, spread or funding. The take-profit comparison is separate from
the scaling and trailing-stop experiments. Parameters are uncalibrated and
not recommendations. Only new validation.4 enrollment receives these outcomes.
Older cohorts and prior evidence remain unchanged. No live order or deployment.

## Combined position management (combined.1, validation.5)
Three paired policies: fixed, hybrid exits without resizing, hybrid exits with
resizing. One normalized FIFO quantity ledger tracks additions, reductions,
partial exits, realized P&L and per-fill fees. Existing stop, partial and
final targets precede discretionary next-open actions. When a stop and a
profit limit are both touched intrabar and sequence matters, exclude and
report the sample. No retrospective fill or stop change. Hybrid trailing
ratchets only and uses updated ATR, EMA9 seed if available, recent structure
and estimated episode breakeven including realized P&L and fees. Target
extension is once only; partial exit is once at half original target distance.
Priority for next-open actions: full giveback exit, reduction, then addition.
No additions after partial or reduction; at most five one-unit additions.
New experimental rule: an addition is accepted only if modeled episode net
P&L at the existing stop, including estimated entry/exit fees for the addition,
is no worse than the initial modeled stop-risk budget. This is not an account
risk limit or a guarantee: gaps, slippage, liquidation and funding are not
modeled; normalized units are not percentages of capital. The initial EMA/ATR
seed is approximate as in stop.1. Costs are proportional to individual fill
notional, so the fixed comparison is specific to this simulator.
Only validation.5 enrollments get combined comparisons; older cohorts remain
unchanged. Results are hypothetical; no broker mutations or deployment.

## Adaptive learning (learning.1)
Read-only chronological report over validation.5 combined-management outcomes.
Explicit UTC epoch cutoff and as-of are required. Training uses only windows
resolved strictly before cutoff; evaluation uses later signal windows resolved
by as-of. Windows straddling the cutoff are excluded. Cohorts separate engine,
scoring and combined versions, strategy family, direction and regime.
All policies must have observed outcomes at 15 and 30 bps on the same window
for a matched comparison. Report exclusions; complete-case selection may bias
the sample. Training selects one policy using at least 30 paired observations,
positive mean return and improvement over fixed at both cost assumptions.
Only that policy is evaluated on the later set, with at least 20 paired windows.
These minimums are provisional, not statistical guarantees. Output reports
mean, median paired difference, positive rate, worst observed return and
additive normalized-notional drawdown, not actual account equity or liquidation.
No parameter updates, automatic promotion or broker writes. Repeatedly moving
the cutoff can contaminate holdout evidence; freeze it before a future study.
The current report compares management variants only; learning entry weights,
indicator ablation, risk-matched exposure and true prospective frozen-policy
deployment remain pending.
    python3 -m recover_trading.gold_v2_learning --journal gold-v2.sqlite --cutoff EPOCH --as-of EPOCH
