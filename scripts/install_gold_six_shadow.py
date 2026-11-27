#!/usr/bin/env python3
"""Install the isolated forward-paper worker alongside recover-demo.service."""
import io
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess
import tarfile
import tempfile
import time

PIN = "ce913f777523d32c17de6357f5d6c9fb2048dd8e"
UNIT = "recover-gold-six-shadow.service"


def main():
    if os.geteuid():
        raise SystemExit("Run with sudo")
    checkout = Path(__file__).resolve().parents[1]
    ctl = subprocess.check_output
    pid = ctl(["systemctl","show","recover-demo.service","-p","MainPID","--value"],text=True).strip()
    proc = Path("/proc")/pid
    argv = (proc/"cmdline").read_bytes().decode().split("\0")
    if "recover_trading.service" not in argv:
        raise SystemExit("Cannot identify running Recover worker")
    data = "data/recover-service"
    for i,arg in enumerate(argv):
        if arg=="--data-dir":
            data=argv[i+1]
        elif arg.startswith("--data-dir="):
            data=arg.split("=",1)[1]
    market=(proc/"cwd").resolve()/data/"XAUTUSD/market.sqlite"
    if not market.is_file() or any(ch.isspace() or ch in '%"\\' for ch in str(market)):
        raise SystemExit("Gold cache path unavailable or unsupported")
    uid=proc.stat().st_uid
    user=pwd.getpwuid(uid).pw_name
    dest=Path("/opt/recover-gold-shadow")
    dest.mkdir(exist_ok=True)
    release=dest/PIN
    if not release.exists():
        stage=Path(tempfile.mkdtemp(dir=dest))
        raw=ctl(["git","-c",f"safe.directory={checkout}","-C",str(checkout),"archive",PIN,"recover_trading","tradebot"])
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(stage,filter="data")
        stage.chmod(0o755)
        stage.rename(release)
    ledger=Path("/var/lib/recover-gold-six-shadow/ledger.sqlite")
    config=f"""[Unit]
Description=Gold six-slot versus starter-only forward paper comparison
After=recover-demo.service
[Service]
User={user}
WorkingDirectory={release}
StateDirectory=recover-gold-six-shadow
ProtectSystem=strict
ProtectHome=read-only
NoNewPrivileges=yes
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 -m recover_trading.gold_six_shadow {market} {ledger}
Restart=on-failure
RestartSec=15
[Install]
WantedBy=multi-user.target
"""
    path=Path("/etc/systemd/system")/UNIT
    path.with_suffix(".pending").write_text(config)
    path.with_suffix(".pending").replace(path)
    subprocess.run(["systemctl","daemon-reload"],check=True)
    subprocess.run(["systemctl","enable",UNIT],check=True)
    started=time.time()
    subprocess.run(["systemctl","restart",UNIT],check=True)
    for _ in range(60):
        if ledger.exists():
            try:
                with sqlite3.connect(ledger.as_uri()+"?mode=ro",uri=True) as db:
                    row=db.execute("SELECT payload FROM checkpoint WHERE id=1").fetchone()
                if row:
                    state=json.loads(row[0])
                    if state["quote"] >= started*1e6 and state["bar"] > started-600:
                        print("SHADOW ACTIVE: fresh Gold quote and completed bar verified",state["bar"])
                        return
            except sqlite3.OperationalError:
                pass
        time.sleep(2)
    raise SystemExit("Installed; fresh Gold quote and bar still unverified. Inspect journalctl -u "+UNIT)


if __name__=="__main__":
    main()
