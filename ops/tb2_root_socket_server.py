#!/usr/bin/python3
"""Private socket adapter for the existing root bridge; systemd activation only."""
import json
import os
import pwd
import socket
import stat
import struct
import subprocess

BRIDGE = "/usr/local/sbin/tb2-root-bridge"
AUTH_FILE = "/etc/tradebot2/root-socket-user"
MAX_REQUEST = 8192
MAX_RESPONSE = 16384


def identity():
    meta = os.lstat(AUTH_FILE)
    if not (stat.S_ISREG(meta.st_mode) and meta.st_uid == 0
            and stat.S_IMODE(meta.st_mode) == 0o600 and meta.st_nlink == 1):
        raise PermissionError("Untrusted root socket identity config")
    with open(AUTH_FILE, "r", encoding="ascii") as f:
        name = f.read(128).strip()
    record = pwd.getpwnam(name)
    if not name or record.pw_uid == 0 or "/" in name:
        raise PermissionError("Invalid peer identity")
    return name, record.pw_uid


def send(conn, obj):
    payload = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    if len(payload) > MAX_RESPONSE:
        payload = b'{"status":"root_bridge_invalid_response","root_access_active":false}'
    conn.sendall(payload + b"\n")


def handle(conn, name, expected_uid):
    conn.settimeout(6)
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    if uid != expected_uid:
        send(conn, {"status": "unauthorized_peer", "root_access_active": False})
        return
    raw = bytearray()
    while b"\n" not in raw:
        block = conn.recv(min(2048, MAX_REQUEST + 1 - len(raw)))
        if not block:
            return
        raw.extend(block)
        if len(raw) > MAX_REQUEST:
            send(conn, {"status": "invalid_request", "root_access_active": False})
            return
    try:
        obj = json.loads(bytes(raw).split(b"\n", 1)[0])
        if not isinstance(obj, dict) or set(obj) != {"command", "timeout_seconds"}:
            raise ValueError("Wrong fields")
        command, seconds = obj["command"], obj["timeout_seconds"]
        if (not isinstance(command, str) or not command.strip()
                or len(command) > 4096 or "\x00" in command
                or type(seconds) is not int or not 1 <= seconds <= 30):
            raise ValueError("Invalid command or timeout")
    except (ValueError, UnicodeError, TypeError):
        send(conn, {"status": "invalid_request", "root_access_active": False})
        return

    # Kernel-authenticated peer identity, not a client-provided sudo user.
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C",
           "LC_ALL": "C", "SUDO_USER": name}
    try:
        result = subprocess.run(
            [BRIDGE, "--timeout", str(seconds), "--", command],
            input=b"", capture_output=True, check=False,
            cwd="/", env=env, timeout=seconds + 5)
        if not result.stdout or len(result.stdout) > MAX_RESPONSE:
            raise ValueError("Missing/oversized bridge reply")
        reply = json.loads(result.stdout)
        if not isinstance(reply, dict):
            raise ValueError("Bad bridge reply")
        send(conn, reply)
    except subprocess.TimeoutExpired:
        send(conn, {"status": "root_bridge_unavailable_or_timed_out",
                    "root_access_active": False})
    except (OSError, ValueError, UnicodeError, TypeError):
        send(conn, {"status": "root_bridge_unavailable_or_rejected",
                    "root_access_active": False})


def main():
    if os.geteuid() != 0:
        raise SystemExit("Must run as root")
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise SystemExit("Must use systemd socket activation")
    name, expected_uid = identity()
    listener = socket.socket(fileno=3)
    while True:
        conn, _ = listener.accept()
        with conn:
            try:
                handle(conn, name, expected_uid)
            except (OSError, ConnectionError, TimeoutError):
                pass


if __name__ == "__main__":
    main()
