#!/usr/bin/env bash
# One-time LOCAL enablement of full root execution via private Tb2.0 MCP.
# This is intentionally an exceptionally privileged access grant. Never use
# for public/shared plugins or hosts that have uncontrolled users.
set -euo pipefail
set +x
umask 077

if [[ "${1:-}" != "--enable" || $# -ne 1 ]]; then
  echo "Usage: bash ops/install_chat_root_bridge.sh --enable" >&2
  echo "Disable any time: sudo rm -f /etc/tradebot2/root-bridge.enabled" >&2
  exit 2
fi
if [[ -n "${SUDO_USER:-}" || $(id -u) == 0 ]]; then
  echo "Run as the ordinary OS user that owns the PRIVATE tunnel, not via sudo." >&2
  exit 2
fi

TUNNEL_OS_USER="$(id -un)"
if [[ ! "$TUNNEL_OS_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
  echo "Unsupported OS user name for sudoers" >&2
  exit 2
fi

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ ! -f "$REPO_ROOT/ops/tb2_root_bridge.py" ]]; then
  echo "Cannot find reviewed root-bridge source" >&2
  exit 2
fi

printf '%s\n' "WARNING: This grants unlimited ROOT execution to the approved private ChatGPT tunnel identity."
printf '%s\n' "The private tunnel must NOT be published/shared. Every root action requires explicit operator request."
printf '%s\n' "Enable for tunnel OS identity: $TUNNEL_OS_USER"

sudo install -o root -g root -m 0755 \
  "$REPO_ROOT/ops/tb2_root_bridge.py" /usr/local/sbin/tb2-root-bridge
sudo install -d -o root -g root -m 0700 /etc/tradebot2

SUDOERS_TMP="$(mktemp)"
trap 'rm -f "$SUDOERS_TMP"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/tb2-root-bridge\n' \
  "$TUNNEL_OS_USER" > "$SUDOERS_TMP"
sudo install -o root -g root -m 0440 "$SUDOERS_TMP" \
  /etc/sudoers.d/tradebot2-chat-root
if ! sudo visudo -c -f /etc/sudoers.d/tradebot2-chat-root >/dev/null; then
  sudo rm -f /etc/sudoers.d/tradebot2-chat-root
  echo "Sudoers validation failed; root bridge not enabled" >&2
  exit 1
fi

# The marker is root-only, not writable by the tunnel or dashboard process.
# Removing it immediately disables the root bridge without deleting source.
sudo install -o root -g root -m 0600 /dev/null \
  /etc/tradebot2/root-bridge.enabled

echo "Root MCP bridge installed and explicitly enabled for: $TUNNEL_OS_USER"
echo "Audit log: /var/log/tradebot2-root-admin.log (root-readable only)"
echo "Disable: sudo rm -f /etc/tradebot2/root-bridge.enabled"
echo "No dashboard, bot, trading or broker settings were changed."
echo "Restart only the PRIVATE tunnel-client process to refresh MCP tool discovery."
