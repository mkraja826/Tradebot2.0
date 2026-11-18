# Continuous BTC crypto opportunities — Delta India DEMO only

**Code ready, offline-tested; no unattended exchange order execution verified or activated.**

## Goal and current state

The user has explicitly replaced the old requirement that new BTC trades must only occur during NYSE cash hours. This is now an **opt-in schedule** `crypto-24x7` for Delta India demo BTC futures/options. It works on weekends and outside NYSE trading hours. The default schedule remains `nyse` to avoid accidentally changing an existing runner.

Two very different runtime modes exist:

| Mode | Runs 24/7? | Calls paid AI? | Opens/cancels/closes Delta orders? |
| --- | --- | --- | --- |
| `run --mode observe --schedule crypto-24x7` | Yes | Yes, per interval if data healthy | **NO** |
| `run --mode demo --schedule crypto-24x7 --demo-execute` | Yes, while process alive | Yes | **YES — not yet exchange integration tested; DO NOT run unattended** |

Both are pinned to the **Delta India testnet only**. No production account support exists.

## Enable the safer 24/7 research scanner on the Iowa VM

After confirming a Top Billing spend cap and Google Cloud billing, connect to Compute Engine SSH and run:

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
bash ops/install_observe_service.sh
```

The service uses `--schedule crypto-24x7`, polls every 60 seconds, and requests a DeepSeek plan at most once per 5 minutes *per uninterrupted process* if the exchange permits. This can produce up to about **288 paid AI completions per 24 hours**, plus extras after restarts. It never sends exchange orders.

```bash
sudo systemctl status tradebot2-observe --no-pager
sudo journalctl -u tradebot2-observe -n 30 --no-pager
```

## 24/7 Demo active trading pilot: code safeguards and release gates

The optional demo executor only permits active orders when **all three** explicit controls are supplied:
- `--mode demo --demo-execute`
- `ENABLE_DEMO_ORDERS=true`
- `--schedule crypto-24x7` plus `ALLOW_CRYPTO_24X7_DEMO=true`

These are NOT enabled by `keys.env` or the observer service.

For the initial testnet pilot, the runner additionally:
- Refuses new entries while any BTC position or pending order exists.
- Enforces at most **4 BTC derivative legs**, **1 contract per leg** (fixed pilot defaults), independently of the AI choice.
- Rechecks quotes and demo wallet status after the AI response and just before order entry; no entry on stale data.
- Exits positions after a **15-minute maximum hold**, by repeated exchange-reconciled closeout attempts. This is NOT an exchange-native guaranteed stop.
- At reboot or process restart, attempts to close any **unknown preexisting BTC position** rather than assuming it is safe to add exposure.
- Persists an account-trading halt marker (`data/trades.jsonl.crypto24x7-halt`) on execution failures, unknown positions or unexpected orders. Do not remove this file until manually inspecting positions, order history, fills and ledger.
- Attempts BTC-only closeout on graceful stop (but a VM outage, exchange outage or force-kill can still leave an exposed demo account).

**Important unverified pieces:** On actual Delta testnet, order fill status responses, cancel semantics, reduce-only position exits, multi-leg partial fills, margin handling, latency/timeouts, and reconciliation after uncertain exchange replies remain untested end-to-end. No independent remote pager/watchdog or verified P&L loss brake is installed. These are blockers for **unattended 24-hour order execution**.

## Next release gate — supervised testnet order lifecycle

Before an unattended trading service, the operator and assistant must run one *supervised* low-size testnet order, verify confirmed fill, verify forced closeout, check remote open orders/positions, and test failure recovery. Run only with a dedicated disposable **demo** account and enough time to intervene manually.

Do NOT put a `demo --demo-execute` command into systemd, cron, screen, tmux or nohup until these checks pass and off-VM alerts are configured. Do not remove the pilot risk limits merely to get more trades.

If testnet returns no usable quotes or DeepSeek cannot supply a complete validated plan, do **not** force a random trade. WAIT is always a valid outcome.

## Scheduling and cost

Crypto derivatives can trade 24/7, but exchange maintenance, illiquid option books and stale tickers can cause the bot to refuse trades. Model calls cost money regardless of trading success. The time-stop caps duration, not financial loss. Limits must be strengthened with position-value, account drawdown, P&L/fee tracking and broker-side stop/alert verification before unattended operation.
