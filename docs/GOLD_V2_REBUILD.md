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

## Demo entry adapter (entry-adapter.1)
Gold V2 candidate preparation can map into the existing DemoExecutor proposal
contract: XAUTUSD only, confirmed USD wallet/account identity, vanilla XAUT
contract, integer quantity, tick-rounded SL/TP and fixed 20x leverage.
Allocation fraction must be supplied explicitly; no live default is selected.
Estimated margin uses current book and contract value, not exchange-approved
margin or liquidation distance. Contradictory directions remain unresolved.
A single deterministic decision ID per five-minute boundary prevents duplicate
journal reservation. The submission bridge is disabled by default and requires
the existing concrete DeltaDemo and DemoExecutor types. Preparation checks
flat exposure and order snapshot completeness; existing unresolved journal
entries prevent dispatch. Main-account exclusion still requires operator
verification of the configured Gold demo account ID and distinct credentials.
Single runtime ownership, lifecycle reconciliation, existing-position handoff,
actual bracket protection and live management integration remain pending.
No CLI or service calls the bridge. Combined simulation is not a live position
manager. BTC, legacy Gold routing, execution files and server are unchanged.

## Gold V2 position-management adapter (management-adapter.1)
Pure proposal adapter accepts a current XAUTUSD position, matching reduce-only
mark-price bracket legs, trusted original V2 journal/receipt evidence, and
contiguous completed episode candles. Verifies original fully filled quantity,
entry price, product, deterministic client ID and supplied position lineage.
The caller still must verify lineage and first full post-fill bar against
trusted exchange fills; this adapter does not retrieve that evidence itself.
It produces at most one existing management-lifecycle-compatible proposal:
maintain, close on close-based giveback, reduce half on adverse movement,
tighten stop, or extend target. Stop edits take priority over target edits
and only one bracket leg changes. The cost-adjusted entry is an approximation.
No live submission, journal staging, reconciliation worker or service route.
The current adapter deliberately cannot adopt legacy positions or continue
after a partial reduction, and cannot execute additions or partial limit exits.
Existing ManagementExecutor supports reduce-only and single-leg amendments,
not verified add-and-rebracket execution. These features require further
ownership and fill-state integration. No runtime changes or BTC changes.

## Position lifecycle (lifecycle.1, management-adapter.2)
Append-only SQLite episode observations preserve a reserved flat-account entry
anchor, terminal entry receipt and full post-anchor fill evidence. Deterministic
client ID, product, side, fill IDs, strict timestamps, cumulative signed
quantity, weighted entry price, authorized terminal reduce-only receipts and
current position/bracket coverage must agree. Canceled partial entry fills
and subsequent verified reductions can retain ownership. Closure requires
flat position and complete empty order observation. Unattributed fills,
ambiguous timestamps, missing coverage and stale observations are not treated
as verified. Journal rejects conflicting reservations, backward observations
and reopening terminal episodes; detects stop loosening between verified
observations. The new management evaluate_episode path reconciles the supplied
evidence and supports continued proposals after reduction, with no second
adverse reduction and no entry-only breakeven approximation after reduction.
Exact weighted price matching is conservative and may reject exchange-rounded
averages. No trusted exchange evidence collector, account binding, atomic
pre-submit reservation, management proposal staging or service integration
is wired yet. The caller must establish complete fill pagination, authentic
authorized reduction receipts and flat anchor; these are not guaranteed by
the pure adapter. Position additions, partial limit placement and automatic
bracket repair remain separate pending work. No deployment or exchange writes.

## Continuous shadow worker (worker.1)
A standalone Linux worker connects market scans, optional cached public feeds,
prospective enrollment, outcome resolution and compact status publication.
Resolution continues independently when the current scan fails. A local
flock prevents two workers sharing the same data directory. SQLite persists
observations across restarts; status is atomically replaced in a dedicated
gold_v2_status.json sidecar. It does not overwrite legacy status.json,
market history, order journals or dashboard files.
Optional authenticated demo reads verify the configured Gold wallet ID and
distinct BTC/Gold credentials. They report position/bracket state and optional
entry-plan availability, not wallet balances, account IDs or raw receipts.
The worker has no execute flag, no order mutation path and no AI calls.
Example from an isolated checkout (not an instruction to replace the service):
    python3 -m recover_trading.gold_v2_worker --data-dir ./data/gold-v2-shadow --once --fundamentals --public-feeds
Omit --once for recurring observation; default interval 60 seconds. No service
installation is performed. Existing dashboard does not yet consume this
sidecar. Trusted episode evidence acquisition, management staging, single
execution ownership, account-bound entry reservation, additions, partial exits
and legacy routing replacement remain pending. Test execution and live feed
availability require verification before deployment.

## Autonomous execution connection (controller.1, worker.2)
The optional injected controller calls the existing DeltaDemo/DemoExecutor
and ManagementExecutor. Disabled unless explicitly enabled by a caller.
The command-line worker still has no execution activation flag. Before entry
dispatch it verifies the configured Gold account, checks unresolved episodes,
orders and management attempts, then durably reserves an account-bound episode
seed. A crash between reservation and order submission requires reconciliation;
the controller never blindly resubmits. An acknowledged order is not proof of
a fill. For owned episodes it collects entry receipt, paginated normalized
fills, verified deterministic management reduction receipts and fresh position/
bracket snapshots. It journals reconciliation, evaluates a single management
proposal, stages it in the existing management_shadow schema and delegates
to the existing single-leg/reduce-only management executor. Proposal IDs and
five-minute buckets are deterministic; no legacy proposal is overwritten.
The worker reports controller status only, with no account IDs or raw receipts.
IMPORTANT unresolved requirements: exchange-triggered protective-order
closure receipts are not yet attributed by this collector. Such a closure may
leave an episode unresolved. A pre-submission reservation without an exchange
receipt also requires explicit recovery. The existing complete-page requirement
can reject large fill histories; the worker's 400-bar history can be insufficient
for long-held episodes. Account-specific ownership across legacy and new
processes is not yet enforced by the worker directory lock. Position additions,
partial limit profit-taking and automatic bracket repair remain unsupported
in the runtime route. Entry/management settings are not selected by learned
performance yet. Do not enable or replace the live service until these
issues, exact deployed revision and full regression tests are addressed.
No server installation, execution activation or exchange mutation performed.

## Exchange reconciliation and recovery (recovery.1, controller.2)
Read previously verified owned-position bracket IDs from the episode journal.
For subsequent fills referencing those IDs, retrieve terminal order receipts
using the documented authenticated GET /v2/orders/{order_id} on the demo host
(https://docs.delta.exchange/). Require matching product, opposite side,
reduce-only mark-price bracket type, prior observation before fill and exact
filled quantity. Pass matched receipts into the existing fill-chain replay.
No unknown order is adopted by inference. This cannot attribute a bracket
that triggers before the first verified open-position observation.
Interrupted reservations can become terminal_no_submission only if the
intact local journal proves no order reservation or a preparation failure,
the exchange explicitly returns order_not_found, a complete fill window has
no post-anchor fills, a fresh snapshot is flat with no orders, and at least
120 seconds have elapsed. A timeout or unknown submission remains unresolved;
never resend blindly. This relies on exclusive runtime ownership and intact
journals. The recovery observation records classification, not a full raw
exchange evidence archive. Verified terminal/owned episode replay can resolve
the corresponding local unknown/submitting order status.
Management attempts still awaiting verification can prevent closure reconciliation;
a crash between terminal episode persistence and order-journal update can
require manual recovery. Same-timestamp fill ordering, large history windows,
unobserved protective legs and automatic bracket repair remain incomplete.
No mutation, deployment or CLI execution activation in this phase.

## Advanced resizing (resize.1, management-adapter.3)
The pure addition preview models one initial-quantity addition per favorable
0.5 ATR increment, up to five additions and no additions after a reduction.
It requires a current matched bracket and fresh quote, reports expected signed
quantity, weighted average entry and unchanged protective triggers, and compares
modeled stop P&L including assumed turnover costs with original stop risk.
These are research quantities and assumptions, not approved capital allocations.
The independent addition verifier checks reserved client identity, terminal
receipt, chronological fills, signed quantity chain, weighted entry, unchanged
target, non-loosened stop and full observed post-fill bracket quantity.
It accepts canceled partial additions for evidence purposes, but the equal
initial-quantity preview does not plan subsequent adds after a partial addition.
Exact decimal comparisons may reject rounded exchange averages. Observed coverage
before and after is NOT proof of uninterrupted protection during resizing.
No add submission, bracket resize mutation or resized episode adoption is wired.
The episode management adapter now proposes one reduce-only partial market
exit when completed close and current mark are both at least halfway toward
the original target. Existing giveback exit takes precedence. Integer half
quantity is rounded down; size one is not reduced. Any previous verified
reduction prevents another discretionary reduction. This reuses the existing
controller and management executor contract; it is not a resting partial
limit order or guaranteed fill at the halfway price. A reduction can leave
bracket coverage unresolved if exchange-side resizing is not verified.
No deployment, live tests, or actual exchange writes. Next: full regression
testing, dashboard read integration, and exclusive Gold cutover preparation.

## Dashboard integration (worker.3, dashboard.1)
Worker publishes bounded technical indicators, macro bias/dollar/real-yield
context, candidate scores and up to 200 paired combined-management groups.
Existing loopback dashboard exposes GET /api/gold-v2 via an allowlisted
projection from gold_v2_status.json. --gold-v2-dir can select a separate
status directory; default is <dashboard data-dir>/gold-v2-shadow.
The live workspace displays an independent read-only panel only when XAUTUSD
is selected. Polls every 15 seconds while visible, marks evidence older than
180 seconds stale, uses textContent rather than injected HTML, and shows
hypothetical bps separately from realized P&L. No balance, account identifier
or raw receipt fields are projected. Existing chart, position panels and
BTC route remain unchanged. SL/TP historical chart overlays and adaptive
learning report visualization are not included in this increment.
The worker still has no CLI execution activation. No server or dashboard
deployment occurred. Browser smoke testing and full regression verification
are outstanding.

## Fast protective closure observation
The controller now attempts a read-only reconciliation immediately after an
acknowledged entry, rather than waiting until the next worker tick. Failure
preserves the acknowledged dispatch status and reserved episode.
If the first reconciliation finds unattributed fills, an independent diagnostic
may identify a possible early protective closure using exact account, original
trigger, reduce-only bracket type, full fill chain and flat/empty snapshot.
It does not grant attribution, mark the episode terminal or authorize another
entry. The documented order schema does not establish a reliable explicit
parent/child link for every early fill. A verified link or previously recorded
protective leg remains necessary. No change to demo activation or live services.

## Production reference research
The live public comparison at commit 237477c found 19/42/45 demo
true-range anomalies versus 0/2/0 production anomalies on 5m/15m/1h,
with only one timestamp-matched anomalous bar. Counts overlap across
timeframes. Production data also has quality issues; do not silently
replace a demo OHLC value or infer its fill price from a reference.
The standalone `python -m recover_trading.gold_v2_reference --once`
collects exact completed production XAUTUSD candles with no credentials,
retains strict engine quality status, and exposes separate descriptive
close-only EMA diagnostics even if range quality is rejected. Reference
reports carry explicit provenance and execution_eligible=false; the
existing demo entry adapter and validation journal refuse them. This is
not yet a production-signal/demo-execution hybrid. A separate prospective
study, quote basis and mark/stop geometry, management price provenance,
and actual demo execution compatibility must be verified before routing.
No changes to the running workers.

## Hybrid price compatibility research (hybrid.1)
The pure preview translates reference ATR / reference candle close to a
fractional volatility measure, then multiplies by the current demo-side
bid/ask entry reference. It records mark and book basis in bps, both
spreads and quote timestamps. Quotes must be individually no older than
30 seconds and paired within five seconds; these are provisional evidence
matching tolerances, not a calibrated profitability policy. It preserves
the reference signal provenance, emits hypothetical tick-rounded SL/TP
levels and checks mark geometry. No basis acceptance threshold is
calibrated, and a large basis is explicitly reported, not silently
treated as equivalent prices. No executable proposal, sizing, account
read or order is produced. This module is not yet integrated into the
worker, management adapter or a persistent prospective hybrid journal.
Reference range anomalies remain unresolved. Next: separate prospective
hybrid validation with observed demo execution-price evidence and a live
quote-pair compatibility probe.

## Mark hybrid macro context (mark-context.1)
The mark research worker now collects published dollar and real-yield
features, public CFTC positioning, token references and other available
context in its independent signal collection task. At quote enrollment
it freezes the available evidence and tags each hypothesis aligned,
opposed, neutral or unknown. Missing or expired macro evidence does not
change a technical hypothesis. The separate hybrid journal summarizes
sampled outcomes by family, direction and macro stratum using the
original enrollment evidence, not subsequent publications.
These comparisons are observational, not causal evidence or an
optimized trading filter. Dollar data is a broad daily dollar index,
not live DXY. Weekly CFTC observations are contextual only. No paid AI,
execution or deployment changes. Slow macro collection can cause signal
expiry; measure this before any continuous deployment.

## Mark hybrid learning (mark-learning.1)
Run `python -m recover_trading.gold_v2_mark_learning --journal PATH --cutoff EPOCH --as-of EPOCH`.
Use a prospectively fixed training cutoff. Only resolved, nonoverlapping
mark-hybrid windows with matching entry and management versions and
complete paired 15/30 bp outcomes qualify. Training observations must
resolve before cutoff; holdout windows must begin at or after cutoff.
Minimum group sizes are provisional 30 training and 20 holdout windows.
The all-sample and macro strata overlap; rankings are descriptive,
selected policies are training-only, and positive holdout observations
do not imply statistical significance or permission to deploy.
No automatic promotion, no real fills, no account-equity estimates.
