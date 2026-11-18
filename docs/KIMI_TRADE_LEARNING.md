# Tradebot 2.0 — GPT-6 autonomy + Kimi evidence-based learning

## Roles and scope

GPT-6 is the sole FIRE decision-maker. FIRE remains research-only until
supervised Delta Demo order execution is separately implemented and verified.
DeepSeek V4.1 Flash remains the 24/7 opportunity scanner.

Kimi K3.1 Pro is a separate **research-only** learning reviewer. It has no
broker order interface and never modifies GPT-6 system instructions. Kimi's
hypotheses have status **candidate**, cannot promote themselves to validated,
and are never automatically fed back to GPT-6. No model fine-tuning occurs.

## Deploy to Google Cloud VM

Run as the same normal SSH user that owns the existing Tradebot installation.
Do not paste keys in chat.

    cd ~/Tradebot2.0
    git pull --ff-only
    source .venv/bin/activate
    python -m pip install -e .

First test one **read-only** broker observation, with zero paid Kimi calls:

    source ~/.config/tradebot2/keys.env
    python -m tradebot.trade_learning_watch

Install and start the separate reboot-safe learning service with model calls
OFF (default):

    bash ops/install_learning_service.sh
    sudo systemctl is-active tradebot2-learning
    sudo journalctl -u tradebot2-learning -n 15 --no-pager

If the operator explicitly chooses to enable paid Kimi reviews on eligible
position events, reinstall only the *learning* service with paid mode ON:

    TRADEBOT_KIMI_PAID_REVIEWS=true bash ops/install_learning_service.sh

The learning watcher polls authenticated Demo BTC data every 30 seconds,
but **never places or cancels orders**. A Kimi completion can be triggered
when BTCUSD exposure is first observed, a position appears flat with no
remaining account orders, a significant price change occurs, or 30 minutes
elapse. There is a durable maximum of **12 paid review reservations per UTC
day**; additional provider-level spend caps are recommended. Timeout and
malformed responses are not silently retried.

Restart dashboard separately to see **Kimi Learning Lab**:

    sudo systemctl restart tradebot2-dashboard
    curl -s http://127.0.0.1:8765/api/learning

The response distinguishes persistent research data from fresh watcher
heartbeats. Database exists does not mean the Kimi watcher is running.
Both demo execution and GPT-6 memory injection remain disabled.

## Confirmed-fill evidence (manual, read-only)

For an independent snapshot of actual Delta Demo BTC fills (up to the last
24 hours), run the following after loading your private shell environment:

    python -m tradebot.trade_fill_evidence --lookback-hours 24

This command uses only signed broker GETs. It does not consume Top Billing
credits, ask Kimi or GPT-6 to make a decision, or place orders. It writes
selected normalized facts to the **immutable unattributed fills** table in
`data/trade-learning.sqlite`; raw broker payloads and account identifiers are
discarded. Repeated observations use exchange fill IDs for deduplication.
The learning dashboard displays **Confirmed fills · unattributed**, separate
from Kimi's evidence records and candidate lessons.

Important: a confirmed fill is not automatically attributed to an observed
trade. The software deliberately does NOT infer net P&L, stop-loss execution,
winning/losing trades, or broker order identity from fills alone. Automatic
trade-level attribution awaits the supervised execution and order-ID
reconciliation milestone.

## Persistence and evidence handling

- Private immutable evidence: data/trade-learning.sqlite, mode 0600.
- Read-only observer heartbeat: data/learning-runtime.json.
- Event types are restricted to selected broker facts with bounded fields.
  Raw API replies, prompts, account secrets, and raw completion bodies are
  never written by this system.
- An entry is only **first observed**, not proven to be the true entry
  timestamp; a flat position is only an observation, not verified realized
  profit or proof that protective orders worked.
- Unverified candidate lessons cannot affect FIRE; no automatic learning
  prompt injection, prohibition of strategies, or hardcoded strategy limits.

## Remaining development work

1. Correlate GPT-6 FIRE requests with idempotent broker order IDs and fills.
2. Verify supervised Delta Demo entry, stop-loss/take-profit attachment,
   partial fills, timeout reconciliation, and final exit.
3. Record authoritative fees, funding, realized P&L, and trade outcomes before
   labeling wins/losses.
4. Evaluate Kimi lessons against later and held-out trades, including missed
   opportunities. Validate/retire lessons independently.
5. Shadow-test baseline GPT-6 versus memory-assisted GPT-6 before enabling
   a reversible, bounded advisory-memory feature.

Keep Cloudflare Access authentication; do not expose port 8765 on the VM.
