#!/usr/bin/env bash
# Opt-in local root socket for the PRIVATE Tb2.0 MCP plugin.
# This authorizes any process running as the selected Linux user to request root.
set -euo pipefail
set +x
umask 077

if [[ $# -ne 1 || "$1" != "--enable" ]]; then
  echo "Usage: sudo bash ops/install_chat_root_socket.sh --enable" >&2
  exit 2
fi
if [[ "$EUID" -ne 0 || -z "$SUDO_USER" || "$SUDO_USER" == "root" ]]; then
  echo "Run via sudo from the VM's private tunnel Linux account" >&2
  exit 2
fi
OWNER="$SUDO_USER"
if [[ ! "$OWNER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
  echo "Unacceptable Linux account name" >&2
  exit 2
fi
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"
if [[ -z "$OWNER_HOME" || ! -d "$OWNER_HOME" ]]; then
  echo "Tunnel account is missing" >&2
  exit 2
fi

REPO_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
SOURCE="$REPO_ROOT/ops/tb2_root_socket_server.py"
PLUGIN="$REPO_ROOT/src/tradebot/chat_plugin.py"
BRIDGE="/usr/local/sbin/tb2-root-bridge"
ENABLE="/etc/tradebot2/root-bridge.enabled"
if [[ ! -f "$SOURCE" || ! -f "$PLUGIN" || ! -x "$BRIDGE" || ! -f "$ENABLE" ]]; then
  echo "Reviewed socket source, plugin, enabled root bridge or marker missing" >&2
  exit 2
fi
if ! grep -Fq 'channel.connect("/run/tb2-root-admin.sock")' "$PLUGIN" &&
   ! grep -Fq "channel.connect('/run/tb2-root-admin.sock')" "$PLUGIN"; then
  echo "MCP handler does not use the private Unix socket; aborting" >&2
  exit 2
fi

echo "WARNING: This gives unrestricted local ROOT execution to the Linux account: $OWNER"
echo "All programs running as that user can access the root socket."
echo "Do not install for a shared account, public tunnel or live trading host."
install -d -o root -g root -m 0700 /etc/tradebot2
install -o root -g root -m 0750 "$SOURCE" /usr/local/sbin/tb2-root-socket-server

TMP_ID="$(mktemp /etc/tradebot2/.root-socket-user.XXXXXXXX)"
trap 'rm -f "$TMP_ID"' EXIT
printf '%s\n' "$OWNER" > "$TMP_ID"
chown root:root "$TMP_ID"
chmod 0600 "$TMP_ID"
mv -f "$TMP_ID" /etc/tradebot2/root-socket-user

cat >/etc/systemd/system/tb2-root-admin.socket <<EOF
[Unit]
Description=Tb2.0 private audited root administration socket

[Socket]
ListenStream=/run/tb2-root-admin.sock
SocketUser=$OWNER
SocketGroup=$OWNER
SocketMode=0600
RemoveOnStop=yes

[Install]
WantedBy=sockets.target
EOF
cat >/etc/systemd/system/tb2-root-admin.service <<'EOF'
[Unit]
Description=Tb2.0 audited root administration service
Requires=tb2-root-admin.socket
After=tb2-root-admin.socket

[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/bin/python3 -I /usr/local/sbin/tb2-root-socket-server
NoNewPrivileges=yes
Restart=on-failure
RestartSec=2
EOF
chmod 0644 /etc/systemd/system/tb2-root-admin.socket /etc/systemd/system/tb2-root-admin.service
systemctl daemon-reload
systemctl enable --now tb2-root-admin.socket

runuser -u "$OWNER" -- python3 - <<'PY'
import json
import socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(12)
try:
    s.connect("/run/tb2-root-admin.sock")
    s.sendall(json.dumps({"command": "id -u", "timeout_seconds": 5}).encode() + b"\n")
    data = bytearray()
    while b"\n" not in data:
        piece = s.recv(2048)
        if not piece:
            break
        data.extend(piece)
        if len(data) > 16384:
            raise RuntimeError("Oversized root bridge response")
finally:
    s.close()
reply = json.loads(bytes(data).split(b"\n", 1)[0])
if (reply.get("status"), reply.get("exit_code"), reply.get("output")) != ("completed", 0, "0"):
    raise SystemExit("Private socket bridge health check FAILED")
print("Private root socket: authorized id -u verified")
PY
echo "No bot services or trading settings were changed."
echo "Revoke all plugin root access: sudo rm -f /etc/tradebot2/root-bridge.enabled"
echo "Updating the socket adapter may require a separately authorized service restart."
