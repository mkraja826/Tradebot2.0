"""Run with sudo from a pinned checkout to activate the BTC demo runner."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

UNIT = "recover-demo.service"
PIN = "554cbbcdb804a374a8bc1c563f41f9b802bb3b66"
DROP = Path("/etc/systemd/system/recover-demo.service.d")
override = DROP / "zzzzzz-btc-scanner-runner.conf"


def ctl(*args):
    return subprocess.check_output(["systemctl", *args], text=True).strip()


def main():
    checkout = Path(__file__).resolve().parents[1]
    raw = subprocess.check_output(["git", "-c", f"safe.directory={checkout}", "-C", str(checkout),
                                   "archive", PIN, "recover_trading"])
    pid = ctl("show", UNIT, "-p", "MainPID", "--value")
    proc = Path("/proc") / pid
    old = (proc / "cwd").resolve()
    if old != Path("/opt/recover-trading/releases/d5a911d"):
        raise SystemExit(f"Unexpected running release: {old}")
    args = (proc / "cmdline").read_bytes().decode().split("\0")
    if "recover_trading.service" not in args or "--execute-demo" not in args:
        raise SystemExit("Unexpected worker command")
    env = dict(x.split("=", 1) for x in (proc / "environ").read_bytes().decode().split("\0") if "=" in x)
    sys.path.insert(0, str(old))
    from recover_trading.service import credentials
    from recover_trading.broker import DeltaDemo
    broker = DeltaDemo(*credentials("BTCUSD", env))
    def flat():
        wallet = [w for w in broker.wallet()["result"] if w["asset_symbol"] == "USD"]
        if len(wallet) != 1 or str(wallet[0].get("user_id")) != "26679287":
            raise ValueError("BTC account mismatch")
        product = broker.product("BTCUSD")["id"]
        pos = broker.positions(product)
        from decimal import Decimal
        if any(Decimal(str(p["size"])) for p in ([pos] if isinstance(pos, dict) else pos)):
            raise ValueError("BTC position is open")
        if broker.active_orders_page(product)["result"]:
            raise ValueError("BTC orders are open")
    flat()
    lines = (DROP / "zzzzz-btc-original.conf").read_text().splitlines()
    cmd, = [x for x in lines if x.startswith("ExecStart=") and x != "ExecStart="]
    if "--lr-v4b-demo" in cmd or "--btc-scanner-runner" in cmd or cmd.endswith("\\"):
        raise ValueError("Unexpected existing override")
    if override.exists():
        raise SystemExit("Runner override already exists; inspect current service status")
    stage = Path(tempfile.mkdtemp(prefix="btc-runner-", dir=old.parent))
    stage.chmod(0o755)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(stage, filter="data")
    body = f"[Service]\nBindReadOnlyPaths={stage}/recover_trading:{old}/recover_trading\nExecStart=\n{cmd} --btc-scanner-runner\n"
    ctl("stop", UNIT)
    try:
        flat()
        with override.open("x") as out:
            out.write(body)
        ctl("daemon-reload")
        ctl("start", UNIT)
        invocation = ctl("show", UNIT, "-p", "InvocationID", "--value")
        for _ in range(120):
            logs = subprocess.check_output(["journalctl", "_SYSTEMD_INVOCATION_ID="+invocation,
                                           "-n","100","-o","cat","--no-pager"],text=True)
            for line in reversed(logs.splitlines()):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event,dict) and event.get("symbol") == "BTCUSD" and event.get("btc_runner_enabled") is True:
                    print({k:event.get(k) for k in ("symbol","btc_runner_enabled","ai_calls","status")})
                    return
            time.sleep(2)
        print("Service started. First BTC runner cycle still unverified; inspect current invocation.")
    except BaseException:
        # Once started, the new worker may already own a position.
        if ctl("show", UNIT, "-p", "ActiveState","--value") in ("inactive","failed"):
            override.unlink(missing_ok=True)
            ctl("daemon-reload")
            ctl("start", UNIT)
        raise


if __name__ == "__main__":
    main()
