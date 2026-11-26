# Tb2.0 liquidation research extension (22 tools total after registration)

Install only in the separate read-only MCP server environment. Keep the current
17 registrations, then before server.run() add:

```python
from recover_trading.tb2_liquidation_tools import register_liquidation_tools
register_liquidation_tools(server,
    data_dir="/var/lib/recover-mcp-snapshots/demo",
    liquidation_dir="/var/lib/recover-mcp-snapshots/liquidation")
```

The second path is a proposed dedicated read-only snapshot directory, not a
verified existing VM path. Operator must locate actual collector databases and
copy events.sqlite, positioning.sqlite and hypotheses.sqlite using SQLite backup
(not raw copying active WAL databases), with read-only access for the MCP user.
Keep per-file snapshot timestamps and acknowledge snapshots are not simultaneous.
Do not expose arbitrary paths or shell access; do not modify trading units.
Run discovery and smoke tests before refreshing the plugin. A missing snapshot
must report unavailable; no fabricated zero events. Snapshot session heartbeat
does not prove live collector health. Only BTC has a configured source.

Tools: liquidation_status, liquidation_history, positioning_history,
liquidation_ema_backtest, liquidation_forward_validation. All history timestamps use UTC epoch seconds, end exclusive;
event receipt must also precede end. Pages limited to 500. Backtest uses existing
fixed-vs-V8 research module, not actual fills or an independent portfolio simulation.
Gold explicitly unavailable until an authenticated-in-provenance market-specific
public source is verified. No order operations.

The forward tool has no mutable strategy arguments. It evaluates the frozen V6
study at the minimum of current time, latest recorded observation, latest
closed 1m candle timestamp and snapshot file timestamps. It returns compact
overall and matched-cohort metrics, primary/reference regime summaries,
opportunity IDs and archive lag. This is a conservative cutoff, not proof of
continuous archive coverage. It never reports a zero sample as a profitable
study. Archive refresh and local discovery must be verified before scheduling
remote reviews. Retain the existing 17 tools and all trading services unchanged.
