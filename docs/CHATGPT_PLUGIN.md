# Trading Bot 2.0 for ChatGPT

The private stdio MCP plugin reads the dashboard on VM loopback port 8765. Fire uses the dashboard's existing demo execution setting, model, market rules and watchdog. The adapter requires no exchange keys. The tunnel profile must be private to the intended operator. Anyone permitted to invoke its write tool can request a demo trade and incur a model call.

## Install on the dashboard VM

Run from your existing checkout as the dashboard user.

```bash
cd ~/Tradebot2.0 &&
git pull --ff-only &&
.venv/bin/python -m pip install -e '.[plugin]' &&
sudo systemctl restart tradebot2-dashboard &&
systemctl is-active tradebot2-dashboard
```

In OpenAI Platform tunnel settings, create a tunnel scoped to your intended ChatGPT workspace and install OpenAI's tunnel-client on the VM. Supply its control-plane key through the tunnel client's supported environment configuration. Keep it out of chat and command history.

```bash
read -rp 'Tunnel ID: ' tradebot_tunnel_id
tunnel-client init --sample sample_mcp_stdio_local --profile tradingbot \
  --tunnel-id "$tradebot_tunnel_id" --mcp-command "$PWD/.venv/bin/tradebot-plugin"
tunnel-client doctor --profile tradingbot --explain
tunnel-client run --profile tradingbot
```

Keep the tunnel client running. In ChatGPT web, open Plugins, choose Add custom MCP server, select Tunnel, choose the tradingbot tunnel and install the plugin in your private workspace. The adapter uses the tunnel access boundary and stdio transport. Do not publish this configuration to a shared audience.

First ask for BTC demo market status and candle coverage. Check the quote timestamp and verify that ChatGPT can retrieve a previous Fire ID from history and review it. The first intentional demo trade is a separate operator action.

## Tools

- `market_status(symbol)` returns a timestamped quote when available, trade levels, current broker position information and the latest Fire status.
- `fire_history(symbol, page)` returns up to 40 receipts per page. Page zero is the most recent.
- `fire_demo(symbol, fire_id)` starts the normal GPT demo workflow for BTCUSD or XAUTUSD. Assign one UUID to each explicit instruction and preserve it with the symbol. Retrying the same pair returns its stored receipt. A fresh ID represents a separate request. A timeout can occur after acceptance. Review the original ID before doing anything else.
- `review_fire(symbol, fire_id)` retrieves the exact recorded decision and asks the broker for evidence on its known order IDs. Closed BTCUSD/XAUTUSD receipts also attempt read-only fill/wallet reconciliation, cached for 60 seconds. Only `is_net_realized_pnl: true` with `financial_reconciliation_status: broker_reconciled` identifies a verified net outcome, including fees and funding as of `reconciliation_as_of_us`. Otherwise the order-level P&L remains explicitly provisional and `reconciliation_reason` explains the gap. External manual closes, unsupported adjustments, or missing identities/position/funding evidence remain unknown. See [reconciliation scope](PROFESSIONAL_UPGRADE.md#increment-8--fill-and-wallet-reconciliation). Compare two trades by reviewing both IDs. Historical protection verification describes the recorded event and current account positions are available separately.

[OpenAI Secure MCP Tunnel setup](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
