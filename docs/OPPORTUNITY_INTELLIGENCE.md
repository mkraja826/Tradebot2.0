# Opportunity intelligence v1 — evidence only
Live diagnostic evidence uses fresh demo mark/bid/ask, current closed-frame ATR,
and nearest observed structure levels above and below the mark. The 15 bps
cost is illustrative, not an exchange fee quote. ATR is realized range,
not expected profit; structural levels are not predicted barriers. Invalid
or stale quotes are unavailable, not substituted. Evidence is displayed
in the existing dashboard and never changes the AI payload, direction,
size, trade frequency, or exchange order policy.
Offline excursion analysis measures maximum favorable/adverse price movements
over the exact replay windows, includes the exit open but not later exit
candle extremes. No intrabar ordering or fill assumptions. Observed
excursions do not imply attainable profits. No fitted weights or stop/target
changes. Reference replay is descriptive because its holdout has been inspected.
