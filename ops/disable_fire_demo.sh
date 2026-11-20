#!/usr/bin/env bash
# Fail-closed disable of NEW Delta Demo FIRE entries.
# Preserve the independent protective watchdog and existing receipts.
set -euo pipefail
set +x
umask 077
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as normal SSH user, not root." >&2
  exit 1
fi

# This operator script only changes dashboard execution permission.
# Check broker exposure first; a dashboard restart is NOT a closeout.
if ! systemctl is-active --quiet tradebot2-fire-watchdog; then
  echo "FIRE watchdog is not active; do not restart dashboard unattended." >&2
  exit 1
fi

# Removing fire-demo.conf alone was insufficient: a different systemd
# EnvironmentFile/source may continue to set the variable to true.
# UnsetEnvironment is applied LAST by systemd, including after EnvironmentFile.
dropin=/etc/systemd/system/tradebot2-dashboard.service.d
sudo install -d -m 0755 "$dropin"
printf '[Service]\nUnsetEnvironment=TRADEBOT_FIRE_DEMO_EXECUTION\n' \
  | sudo tee "$dropin/99-fire-disabled.conf" >/dev/null
sudo chmod 0644 "$dropin/99-fire-disabled.conf"
# Remove the legacy manual opt-in drop-in, if it is present.
sudo rm -f "$dropin/fire-demo.conf"
sudo systemctl daemon-reload
sudo systemctl restart tradebot2-dashboard
if ! systemctl is-active --quiet tradebot2-fire-watchdog; then
  echo "WARNING: watchdog became inactive during dashboard restart!" >&2
  exit 1
fi

# Read only: must confirm BOTH markets have manual execution disabled.
python3 - <<'PY'
import json
from urllib.request import urlopen
for symbol, path in (
    ("BTCUSD", "/api/fire"),
    ("XAUTUSD", "/api/fire/XAUTUSD"),
):
    with urlopen("http://127.0.0.1:8765" + path, timeout=8) as res:
        receipt = json.load(res)
    if receipt.get("execution_enabled") is not False:
        raise SystemExit(symbol + ": FIRE disablement NOT VERIFIED")
    print(symbol + ": NEW FIRE DISABLED")
PY
echo "Independent watchdog remains running; no broker orders modified."
echo "Do not re-enable until the separate supervised 20x commissioning is complete."
