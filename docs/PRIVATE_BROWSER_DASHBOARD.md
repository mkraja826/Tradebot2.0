# Tradebot 2.0 — private browser dashboard

**Code complete; VM activation is a separate user action.** The dashboard is read-only, backed by genuine Delta India demo GET endpoints and local bot/ledger files. It does not place, cancel, close or modify orders.

## What's displayed

- 24/7 observer / supervised demo runner process heartbeat, activity, age, and operating schedule. A timestamp older than 180 seconds is marked **stale**, rather than falsely claiming 24/7 uptime.
- BTCUSD testnet bid/ask quotes, including freshness checks. Unavailable, crossed or stale quotes render as unavailable instead of imaginary prices.
- Signed read-only Delta Demo account position and open-order counts, plus demo net equity where available.
- Latest AI decision, rationale and *proposed* BTC legs, clearly distinguished from broker-confirmed fills and order events.
- Recent curated audit events including execution errors, persistent halts, entry/exit attempts.
- Confirmed fill count and commission totals if a local `confirmed-fills.sqlite` ledger already exists. Equity chart shows **recorded account equity**, never realized trading profit or a fabricated chart.

The web API reads the local `data/trades.jsonl`, `data/runtime.json`, `data/confirmed-fills.sqlite`, and Delta testnet **GET** endpoints. It never reads or transmits your API credentials to the browser. The service runs as your existing VM SSH user with protected credentials in its process memory; avoid granting users shell/VM access.

## Install on the Iowa VM

In the existing VM SSH terminal:

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
bash ops/install_dashboard_service.sh
```

Check:

```bash
sudo systemctl status tradebot2-dashboard --no-pager
curl -I http://127.0.0.1:8765/
```

Expected: service `active (running)`, local response `HTTP/1.0 200 OK`. It auto-starts on VM boot and runs independently of the browser tab. To see errors:

```bash
sudo journalctl -u tradebot2-dashboard -n 30 --no-pager
```

To stop:

```bash
sudo systemctl disable --now tradebot2-dashboard
```

**Important:** `http://127.0.0.1:8765/` is accessible only on the VM, **not in Chrome on your Android phone**. This is deliberate. We must set up private remote access next. Do NOT open GCP firewall port 8765 or change the bind address to `0.0.0.0`.

## Access securely from your Android browser

**Recommended: Cloudflare Tunnel + Cloudflare Access**, using your Cloudflare-managed domain. This needs the account owner's approval and setup. Do **not** publish the tunnel before protecting the hostname with an Access allow policy.

1. In Cloudflare Zero Trust, first create a **self-hosted Access application** for your chosen hostname, e.g. `tradebot.micirql.com`, requiring your own email identity and preferably two-factor authentication. Set an explicit **Allow** policy for your email and no anonymous/bypass rule.
2. Create a Cloudflare Tunnel for the Iowa VM under Zero Trust → Networks → Tunnels. Install `cloudflared` on the VM using Cloudflare's current installation instructions; run the connector setup using your private tunnel token. **Do not paste the token in chat, GitHub, or screenshots.**
3. Set the tunnel's public hostname to the SAME protected name (`tradebot.micirql.com`). Route its origin to `http://127.0.0.1:8765`. Enable Cloudflare's Access protection and confirm the Access policy works before using the link.
4. Allow that exact domain through the dashboard's Host-header guard by reinstalling its systemd service from the VM SSH terminal:
   ```bash
   cd ~/Tradebot2.0
   TRADEBOT_DASHBOARD_ALLOWED_HOST=tradebot.micirql.com bash ops/install_dashboard_service.sh
   ```
5. Open `https://tradebot.micirql.com` on your phone, complete Access login, and view the dashboard. **This URL will not work until you actually configure DNS, Cloudflare Tunnel and Access.** Choose a different hostname if you prefer; replace it in both configurations.

Cloudflare access to the hostname is an authentication layer **outside the app**. Without it the dashboard has no built-in user login. Cloudflare Tunnel alone is **not** sufficient: do not expose balances, positions or AI decisions to the public internet.

## Performance and costs

The dashboard refreshes its display every 10 seconds; broker GET results are cached and refreshed at most once every 20 seconds while a browser is open. Normal page views **never invoke a paid model completion**. The explicit **FIRE · Analyze only** button now requests **GPT-6 only** (up to one paid Top Billing completion) from a fresh Delta Demo BTCUSD snapshot. Kimi is disabled for FIRE: the server rejects unexpected model routes even if stale environment settings exist. Results are research proposals only and **never place or modify exchange orders**. A five-minute server-side cooldown prevents rapid repeat requests; Top Billing spend limits are still recommended. Normal Delta rate limits apply. Cloudflare Tunnel, cloud VM and any external hosting can incur plan-specific costs. The dashboard doesn't start the trading bot; separately use the observer service or supervised demo trading workflow.

Do not present account net equity changes as realized P&L. If the confirmed-fill database has no entries, the dashboard honestly shows zero confirmed fills; this does not mean no exchange fills exist until reconciliation has run.

## FIRE AI comparison (read-only commissioning)

After completing Cloudflare Access login, the dashboard includes a **FIRE · Analyze only** section. Pressing the button requires an explicit confirmation that one paid GPT-6 Top Billing completion may occur. The dashboard displays GPT-6's BTCUSD directional plan, contract count, stop-loss and target (if valid). Kimi is **not requested**. GPT-6's research plan is **not** submitted to Delta. The button cannot start autonomous trading. Invalid model responses display a validation failure, not a fabricated recommendation.

The background model requests are only launched by a same-origin POST with a specific custom action header and no request body; cross-origin forms and unsupported HTTP routes cannot start them. Cloudflare Access must remain configured to allow only the account owner's email. Do not expose the VM's loopback dashboard as a public unauthenticated service. Model requests and costs are not capped by the VM UI beyond its short cooldown: configure a provider-side budget.

Run the updated code on VM with `git pull --ff-only`, `python -m pip install -e .`, then `sudo systemctl restart tradebot2-dashboard`. **This restarts only the web dashboard; it does not restart the observer or enable demo order execution.**
