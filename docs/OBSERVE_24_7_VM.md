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
tradebot run --mode observe --poll-seconds 60 --ai-interval-seconds 3600 --max-options 32
```

Behavior:
- Runs continuously while the VM is on; starts automatically when the VM boots and restarts after process failure (45-second delay).
- Outside NYSE trading-entry hours, checks existing demo account BTC positions and pending orders approximately every 60 seconds; logs an alert if BTC exposure remains outside the session. **Cannot close those positions in observe mode.**
- During the NYSE entry window, requests fresh market data and asks the Top Billing DeepSeek model for a **non-executable proposal roughly once an hour per uninterrupted process**, if the data and account state are healthy. An invalid AI response is rejected; no trade occurs.
- **Billing warning:** Top Billing model proposals incur charges. Restarting the process resets the in-memory AI cooldown, potentially increasing calls; set an external Top Billing key spend limit to avoid surprises.
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

This is a **monitoring/research deployment**. Enabling unattended demo execution would require additional verified trade/fill API integration, independent emergency closeout, alerts and remote watchdog. Do not flip `ENABLE_DEMO_ORDERS` to true or change this service to `--mode demo`.
