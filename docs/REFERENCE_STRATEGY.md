# Matched reference strategy observation
Run the existing registry over separate temporary candle-only snapshots from aligned demo and public reference candles. Five-minute and daily warmup are matched; fallback windows are explicit. Compare per-rule/frame availability and directions; matched consensus uses only comparable rows, with each source's regime. No full live consensus claims, external data fabrication, AI requests or execution changes. Collect every 15 minutes and archive comparison rows and window hashes, not raw reference windows.

Use the latest stored completed demo 5m boundary if the timer fires before a new candle is ingested; record lag relative to the expected boundary. Both sources use this same cutoff.
