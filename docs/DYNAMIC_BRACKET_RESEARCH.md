# Dynamic bracket research
Compare five predefined ATR/structure distance hypotheses against the
same Engine 2.0 reference replay windows. ATR uses 250 consecutive
completed 15-minute candles, with Wilder ATR14. Structure uses the
previous 20 candles excluding the most recent completed candle. Distances
are calculated at decision time and applied as percentage distances
from delayed entry. Missing evidence excludes a window from all alternatives
and the baseline. Stop-first and target-first assumptions reuse the
existing bracket simulator. Rank development results only; report
previously inspected holdout descriptively. No AI, order access,
weight changes or deployed execution changes. This is not a trailing-stop
or optimized-entry simulator.
