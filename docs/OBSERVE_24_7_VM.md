# 24/7 VM uptime for Tradebot 2.0 — read-only observer

**Prepared, not started by GitHub.** This deployment is activated on the Google Cloud Iowa Debian VM by its SSH user. The service is a **continuous read-only observer**, NOT autonomous trading. It never submits or cancels an order and never switches to the production Delta endpoint.

## Start once, using VM SSH

The prior setup stored all three keys in a private file at `~/.config/tradebot2/keys.env`. Do not paste any secrets into chat or the repository.

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
bash ops/install_observe_service.sh
```

The installer uses `sudo` only for the systemd service file and service controls. It **does not create or show credentials**. You do not need to keep your Android SSH terminal open afterwards.

The service uses `ops/run_observe.sh` as its entrypoint. It sources the protected user-owned credentials file inside the service process and immediately forces `ENABLE_DEMO_ORDERS=false`, then executes:

```bash
tradebot run --mode observe --schedule crypto-24x7 --poll-seconds 60 --ai-interval-seconds 1800 --max-options 32
```

Behavior:
- Runs continuously while the VM is on; starts automatically when the VM boots and restarts after process failure (45-second delay).
- Runs on weekends and outside NYSE hours, checking demo BTC account state on each 60-second poll. An existing open order can block new AI analysis. **Observe mode cannot close positions or cancel orders.**
- Around the clock, requests fresh BTC market data and asks DeepSeek for a **non-executable proposal roughly once every 30 minutes per uninterrupted process** if data/account health checks pass. Invalid responses and stale market quotes are rejected; no trade occurs.
- **Billing warning:** Top Billing model proposals incur charges. At 30-minute intervals this can mean up to about 48 paid proposals per day, possibly more after restarts; set an external Top Billing key spend limit before enabling the service.
- Is independent of your browser/phone being connected. However, VM shutdown, Google Cloud billing suspension, outages, CPU/memory pressure, or lack of Delta connectivity can interrupt service availability. Automatic process restarts **do not guarantee 100% uptime**.

## Check and control it (no secrets printed)

```bash
sudo systemctl status tradebot2-observe --no-pager
sudo journalctl -u tradebot2-observe -n 20 --no-pager
```

See whether the VM will start the service at boot:

```bash
sudo systemctl is-enabled tradebot2-observe
```

Stop the observer until you choose to resume:

```bash
sudo systemctl stop tradebot2-observe
```

Resume:

```bash
sudo systemctl start tradebot2-observe
```

Stop and disable automatic startup:

```bash
sudo systemctl disable --now tradebot2-observe
```

To pick up future code changes, pull and reinstall while in VM SSH:

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
bash ops/install_observe_service.sh
```

## Google Cloud checks still needed

- Verify this is the expected `us-central1` Iowa VM and the machine type is `e2-micro` if you intend to use an eligible Google Cloud Free Tier setup. Compute, disk, egress and external IPv4 may incur charges depending on your configuration; do not assume this is free.
- Confirm the VM's outward public IPv4 is **reserved as static**, so stopping/restarting the VM does not invalidate Delta's API IP whitelist.
- Ensure any earlier Mumbai VM is not accidentally still running and accruing charges.
- Keep `keys.env` with file mode `600` and never grant SSH access to untrusted parties.
- Review Top Billing provider-side spend limits before leaving hourly AI inference on.

This is a **monitoring/research deployment**. An explicit `--schedule crypto-24x7` demo execution pilot is in development with one-contract-per-leg caps, four legs maximum, 15-minute time stop and a persistent failure lock. **This has not been exchange-verified or activated.** Before unattended execution, verify real Delta testnet order fill/cancel/closeout, add an independent emergency watchdog and remote alerts, and review the trading risk limits. Do not flip `ENABLE_DEMO_ORDERS` in this service or change the service to `--mode demo`.
