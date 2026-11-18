# Supervised first real Delta India DEMO order attempt (24/7)

This is a **real testnet order-permitted run**, not a guaranteed fill and not an autonomous deployment. The user has explicitly requested active trading around the clock. Before enabling unattended demo execution we need evidence for the whole broker lifecycle: account initially flat, accepted order, verified fill, confirmed reduce-only exit, account finally flat, and recovery after errors.

## Before starting

- Use the **Delta India DEMO account only**, with an isolated key granted testnet trading privileges and the Iowa VM's static public IP whitelisted. Prior signed wallet/orders/positions GET tests were successful, but the POST/DELETE lifecycle has **never been verified** with this broker.
- If you previously enabled the read-only systemd observer, stop it first. Do not run two bot processes against the same dedicated demo account.
- Keep the SSH terminal open and remain available for all 20 minutes. Do not launch this via cron, systemd, `nohup`, `screen` or `tmux` yet.
- The script sources previously imported credentials from `~/.config/tradebot2/keys.env` (private, on the VM). No need to paste any API keys or secrets.
- The pilot will check for no open orders or BTC exposure **before** and **after** the test. It uses Delta testnet only.

## In the VM SSH terminal

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
sudo systemctl stop tradebot2-observe 2>/dev/null || true
bash ops/run_supervised_demo_pilot.sh
```

The script requests at most **one paid DeepSeek AI plan** during its 20-minute window (1-hour cooldown). A valid plan containing up to **four legs of one contract each** may produce real **demo** market orders; WAIT, stale quotes, invalid JSON, missing API trading permission, or insufficient demo margin can result in **zero orders**. No strategy is guaranteed to profit. The position time-stop is **5 minutes**, plus bounded shutdown closeout attempts. The test can be interrupted with Ctrl+C, but no exchange or cloud outage can guarantee every order exits.

Read-only final remote-account check:

```bash
source ~/.config/tradebot2/keys.env
python -m tradebot.pilot_verify
```

The only acceptable success state is `"verified_flat": true` with zero `btc_open_positions` and zero `account_open_orders`. This *does not* prove a round-trip was completed: check journal events for `entry_filled`, `exit_submitted` and `btc_flat_verified` and validate the broker's actual fill IDs and fees separately.

Inspect the last bot journal items, without exposing private balance details:

```bash
tail -n 20 data/trades.jsonl
```

If there are orders or positions left open, or the script logs `TRADEBOT CRITICAL`, immediately check the **Delta DEMO UI** and manually intervene. **Do not restart the demo runner or delete the persistent halt marker until all remote positions and orders are verified flat.**

## After a successful supervised round-trip

Only then consider a dedicated 24/7 demo execution systemd service, with additional independent account monitoring, remote emergency alerts, verified broker stop/cancel behavior and drawdown constraints. The current observer service is 24/7 but cannot submit orders. Importantly, the fixed-size pilot checks a *contract count*, **not risk/value or total notional exposure**; it is not sufficient to remove those controls.

This procedure does not operate a live Delta account or authorize unrestricted real-money trading.
