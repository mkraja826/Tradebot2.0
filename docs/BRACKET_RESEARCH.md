# Bracket research v1
This offline research compares nine fixed stop/target scenarios on the exact
original Engine 2.0 reference replay entries and holding horizons. The
five-minute path is checked in chronological order; the exit candle is
evaluated at its open only. When both barriers are reached in a candle,
report stop-first and target-first assumptions separately. Gap stops use
the opening price and gap targets use the original target. Estimated round
trip cost is deducted once per outcome. Actual fills, mark-price triggers,
funding and liquidation are not modeled. Earlier exits do not permit
additional entries. Development-only selection ranks mean net returns;
the previously inspected holdout is descriptive and not fresh validation.
No changes to demo order execution, AI prompts or weights. Entry timing
and dynamic ATR-based exits remain separate research milestones.
