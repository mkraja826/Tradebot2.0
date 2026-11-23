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

## Optional owner-approved ROOT shell administration (unrestricted, extremely privileged)

The owner explicitly requested and approved a **full VM root shell via the
private Tb2.0 ChatGPT plugin** on 22 November 2026. This is a different trust
scope from `fire_demo`: the plugin may be able to read all machine files,
including broker/API credentials, and replace or destroy any VM service or
data. If the tunnel or ChatGPT account is compromised, the VM is compromised.
**Never publish/share this private tunnel or plugin. Do not use on a live
trading VM until re-reviewed.** Root permission does **not** authorize trades
or weakening the independent trading-risk controls.

The code only provides a secure *mechanism*, not root permission automatically:
the current installed stdio plugin must be updated, and the VM owner must
install the helper under root ownership. No root privileges are supplied by
a GitHub merge or by ChatGPT alone.

### One-time VM bootstrap by the private tunnel's OS user

If the private tunnel and Tradebot currently run using the existing original
checkout, first ensure it is clean and intentionally update that checkout
to a reviewed main commit. Do not overwrite uncommitted work or change
deploys/services during an active trade:

```bash
cd "$HOME/Tradebot2.0"
git status --short
git pull --ff-only
.venv/bin/python -m pip install -e '.[plugin]'
bash ops/install_chat_root_bridge.sh --enable
sudo bash ops/install_chat_root_socket.sh --enable
```

**Important:** use the ordinary operating-system user whose private
`tunnel-client run --profile tradingbot` process launches the
`tradebot-plugin` MCP command. Do not run the installer itself under sudo,
and do not change to an unrelated user: sudoers grants permission ONLY
to that named OS identity. The installer will ask for normal local sudo
permission. It installs a reviewed, root-owned executable at
`/usr/local/sbin/tb2-root-bridge`, sudoers allowlist at
`/etc/sudoers.d/tradebot2-chat-root`, and a root-only enable marker at
`/etc/tradebot2/root-bridge.enabled`. It does not enable FIRE, place a
broker order, modify keys or restart the dashboard.

The tunnel runs with Linux `NoNewPrivs=1`, so it cannot use `sudo` from its
child MCP process. The separate **root-owned socket-activated adapter** is
mandatory for this deployment. The installer checks the socket-enabled MCP
handler, installs `ops/tb2_root_socket_server.py` root-owned and enables
`tb2-root-admin.socket`; it verifies `id -u` through the socket. It does
not modify trading services, broker settings or keys. Its service does not
bind a TCP port. The adapter authenticates the peer's kernel-supplied UID
via `SO_PEERCRED` against a root-owned 0600 user identity file. The existing
root-only enable marker and audit log still apply.

**Security limit:** Every local process running as that authorized Linux user
can request unrestricted root commands through the 0600 socket, including
processes unrelated to ChatGPT. Do not run untrusted workloads as that user;
use a dedicated tunnel OS account for stronger isolation. `NoNewPrivileges`
on the tunnel does **not** protect against requests to the separate root
service. The command-log hashes are not tamper-proof.

Restart **only the private tunnel-client/MCP stdio process** using the
existing method employed on the VM when source changes; reconnect/refresh
Tb2.0 in ChatGPT so that `admin_root_shell` appears. The pre-existing version of
the plugin will not gain this tool until a new process loads the updated
source. A GitHub merge alone changes neither the live dashboard nor plugin.

### How root administration works

- New tool: `admin_root_shell(command, timeout_seconds)`, with a 1–30
  second timeout and at most 4,096 characters of command text.
- The MCP process connects only to `/run/tb2-root-admin.sock` (0600). The
  root-owned service validates the peer UID and request then invokes the
  existing root-owned `/usr/local/sbin/tb2-root-bridge` with a fixed environment.
  Neither dashboard HTTP routes nor the public web app expose shell access.
- Caller cannot select an arbitrary bridge path, hostname, sudo user,
  environment, working directory or command interpreter binary.
- Root helper launches `/bin/bash` with a cleared secret-free environment,
  bounded execution, best-effort redacted/truncated output and a private
  `/var/log/tradebot2-root-admin.log` audit of *command hashes*, timestamps,
  sudo identity and outcome. Root commands can themselves alter these
  facilities; auditing is not tamper-proof. Output redaction is **not a
  guarantee** against deliberate secret exfiltration. Never instruct the
  plugin to print broker secrets, passwords, tokens or private keys.
- ChatGPT must request explicit permission for each destructive action,
  including broker mutations, service changes and deletes. The initial
  owner root-access grant is not permission to execute any particular trade.
- Privileged execution fails closed if the root-only enable marker or
  authorized local socket is missing; the private tunnel must remain private.
  Do not add a generic HTTP shell endpoint.

### Immediate revocation and incident recovery

To revoke the plugin's ROOT execution authority **without restarting
the trading dashboard**, run once via SSH:

```bash
sudo rm -f /etc/tradebot2/root-bridge.enabled
```

To also stop the root socket service (without affecting the dashboard):

```bash
sudo systemctl disable --now tb2-root-admin.socket tb2-root-admin.service
```

For permanent removal also delete the sudoers allowlist, root socket adapter
and root bridge executable, then revoke/rotate the tunnel credential. If the private plugin
was shared unintentionally, revoke the tunnel access immediately; do not
assume disabling a process whose host is already compromised is sufficient.

This full-root path is separate from the one-time isolated-mode PUT
attempt already consumed. Do not remove
`data/main-demo-isolated-reaffirm-once.lock` or bypass BTC's normal
signed-margin, equity, exposure or SL/TP gates merely because root access
is available.
