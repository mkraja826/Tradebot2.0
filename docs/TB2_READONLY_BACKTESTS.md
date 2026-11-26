# Tb2.0 read-only backtests

Separate MCP server only. Do not deploy this branch to recover-demo.service. Register the existing nine intelligence tools and then call register_backtests(server, data_dir="/var/lib/recover-mcp-snapshots/demo", learning_dir="/var/lib/recover-mcp-snapshots/outcome-learning") before server.run(). Install the candidate package in a separate root-owned versioned directory. Keep the old server file as rollback. Run unit tests and a local MCP discovery/smoke check as support before refreshing plugin tools. No change to the trading symlink, systemd trading unit, AI provider or database schema.

Four tools:
- historical_candles: max 500 rows per page; UTC seconds, end exclusive, only completed bars.
- ema_backtest: one frame, matched fixed original bracket versus 8 adaptive variants.
- trade_replay: one exact decision id, per-variant exit details.
- backtest_comparison: six frames, aggregate only.

V1-V4 use immediate trailing EMA9 with 0, .25, .5, 1 ATR14 buffer respectively. V5-V8 use the same buffers after a closed post-entry minute reaches fee-adjusted break-even including 2bps adverse slippage. The initial AI stop never widens. Original TP by default; optional fixed or dynamic EMA21 target is experimental and limits the cohort to valid initial targets. Original bracket takes priority at the next open. Stop-first on dual touch. Historical blend of actual fees applied to simulated notional plus 0/2/5 bps adverse exit slippage.

Original 45-trade study: use start=1795564800 (25 November 2026 00:00 UTC) and end=1795673814 for BTC (26 expected), end=1795674088 for Gold (19 expected); end is exclusive and includes each last original close. Use expected_count to detect missing/rolling episodes. Results compare only identical eligible trades within one frame. Time cap at last full minute before actual close. Not an independent strategy or portfolio backtest; no proof of executable returns. Snapshot signatures detect concurrent replacement during read, but the individual database copies are not a simultaneous snapshot. No broker/provider calls or database writes.