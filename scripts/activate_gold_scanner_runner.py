"""Run with sudo from a pinned checkout to activate the Gold demo volatility trail."""
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
PIN = "dbe2e23523254778cc48b25e13d479ce43e80faf"
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
    broker = DeltaDemo(*credentials("XAUTUSD", env))
    def flat():
        wallet = [w for w in broker.wallet()["result"] if w["asset_symbol"] == "USD"]
        if len(wallet) != 1 or str(wallet[0].get("user_id")) != expected:
            raise ValueError("Gold account mismatch")
        spec = broker.product("XAUTUSD")
        if spec["symbol"] != "XAUTUSD" or spec["contract_unit_currency"] != "XAUT" or spec["settling_asset"]["symbol"] != "USD" or spec["notional_type"] != "vanilla":
            raise ValueError("Gold contract specification mismatch")
        product = spec["id"]
        pos = broker.positions(product)
        from decimal import Decimal
        if any(Decimal(str(p["size"])) for p in ([pos] if isinstance(pos, dict) else pos)):
            raise ValueError("Gold position is open")
        if broker.active_orders_page(product)["result"]:
            raise ValueError("Gold orders are open")
    expected = input("Enter your GOLD demo subaccount numeric user ID: ").strip()
    if expected != "62702465":
        raise SystemExit("Invalid Gold subaccount ID")
    flat()
    original = override.read_text()
    lines = original.splitlines()
    cmd, = [x for x in lines if x.startswith("ExecStart=") and x != "ExecStart="]
    if "--lr-v4b-demo" in cmd or "--btc-scanner-runner" not in cmd or cmd.endswith("\\"):
        raise ValueError("Unexpected existing override")
    gold_flags = [arg for arg in cmd.split() if arg.startswith("--gold-scanner-account")]
    if gold_flags and gold_flags != [f"--gold-scanner-account={expected}"]:
        raise ValueError("Unexpected Gold account configuration")
    if not gold_flags:
        cmd += f" --gold-scanner-account={expected}"
    stage = Path(tempfile.mkdtemp(prefix="btc-runner-", dir=old.parent))
    stage.chmod(0o755)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(stage, filter="data")
    body = f"[Service]\nBindReadOnlyPaths={stage}/recover_trading:{old}/recover_trading\nExecStart=\n{cmd}\n"
    ctl("stop", UNIT)
    try:
        flat()
        tmp = override.with_suffix(".pending")
        tmp.write_text(body)
        tmp.replace(override)
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
                if isinstance(event,dict) and event.get("symbol") == "XAUTUSD" and event.get("gold_runner_enabled") is True:
                    print({k:event.get(k) for k in ("symbol","gold_runner_enabled","ai_calls","status")})
                    return
            time.sleep(2)
        print("Service started. First Gold runner cycle still unverified; inspect current invocation.")
    except BaseException:
        # Once started, the new worker may already own a position.
        if ctl("show", UNIT, "-p", "ActiveState","--value") in ("inactive","failed"):
            override.write_text(original)
            ctl("daemon-reload")
            ctl("start", UNIT)
        raise


if __name__ == "__main__":
    main()
