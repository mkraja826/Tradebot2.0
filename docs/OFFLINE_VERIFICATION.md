# Offline verification

Run python -m unittest discover -s tests -v and node --check recover_trading/dashboard_static/app.js.
The integration tests use actual decision, execution, lifecycle and dashboard journals
with a deterministic scanner report, stub AI and simulated exchange transport.
They assert one POST across restarts, lost-response reconciliation, filled order state,
position margin, observed bracket legs, deduplicated fills, independent BTC and Gold
storage, dashboard read-only HTTP and host checking. No network exchange or AI calls.

Earlier CI failures in the lifecycle and dashboard commits were caused by the restart
assertion counting GET /v2/orders along with POST /v2/orders; the corrected fixture
also distinguishes these paths. This is a test repair, not a trade policy change.
Offline tests cannot prove testnet endpoint compatibility, real contract size/margin,
bracket linkage, provider responses, actual trade profit or browser layout.
