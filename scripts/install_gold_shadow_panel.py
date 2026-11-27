"""Install a read-only Gold comparison panel into the running Recover dashboard."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import urlopen

CHANGES = json.loads("[[\"dashboard.py\",\"def handler(root,\",\"def gold_shadow_snapshot():\\n    ledger = Path(\\\"/var/lib/recover-gold-six-shadow/ledger.sqlite\\\")\\n    try:\\n        with closing(sqlite3.connect(ledger.as_uri()+\\\"?mode=ro\\\", uri=True, timeout=0.5)) as db:\\n            db.execute(\\\"BEGIN\\\")\\n            row = db.execute(\\\"SELECT payload FROM checkpoint WHERE id=1\\\").fetchone()\\n            if not row:\\n                return {\\\"status\\\": \\\"starting\\\"}\\n            state = json.loads(row[0])\\n            events = []\\n            for stamp, kind, payload in db.execute(\\n                \\\"SELECT stamp,kind,details FROM events WHERE kind != 'quote_gap' ORDER BY rowid DESC LIMIT 8\\\"\\n            ):\\n                detail = json.loads(payload)\\n                events.append(dict(stamp=stamp, kind=kind, book=detail.get(\\\"book\\\"),\\n                                   quantity=detail.get(\\\"contracts\\\"), price=detail.get(\\\"price\\\")))\\n        quote = state[\\\"quote\\\"]/1e6\\n        return dict(status=\\\"fresh\\\" if 0 <= time.time()-quote <= 120 else \\\"stale\\\",\\n                    quote=quote, bar=state[\\\"bar\\\"], mark=state.get(\\\"mark\\\"),\\n                    setup=state.get(\\\"setup\\\"), slots=state.get(\\\"slots\\\",0) if state[\\\"active\\\"] else 0,\\n                    books=state[\\\"books\\\"], events=events)\\n    except (OSError, sqlite3.Error, KeyError, ValueError, TypeError):\\n        return {\\\"status\\\": \\\"unavailable\\\"}\\n\\ndef handler(root,\"],[\"dashboard.py\",\"data={\\\"generated\\\":int(time.time()),\\\"markets\\\":[report(root,s) for s in MARKETS]}\",\"data={\\\"generated\\\":int(time.time()),\\\"markets\\\":[report(root,s) for s in MARKETS],\\\"gold_shadow\\\":gold_shadow_snapshot()}\"],[\"dashboard_static/index.html\",\"<section class=\\\"panel\\\"><h2>Account balances</h2>\",\"<section class=\\\"panel\\\" id=\\\"goldPaper\\\" hidden><h2>Gold shadow comparison</h2><p id=\\\"goldPaperState\\\"></p><div id=\\\"goldPaperBooks\\\"></div><h3>Recent paper events</h3><div id=\\\"goldPaperEvents\\\"></div></section><section class=\\\"panel\\\"><h2>Account balances</h2>\"],[\"dashboard_static/app.js\",\"function render(){\",\"function goldPaperView(m){\\n const panel=$(\\\"goldPaper\\\");\\n panel.hidden=m.symbol!==\\\"XAUTUSD\\\";\\n if(panel.hidden)return;\\n const s=data.gold_shadow||{};\\n const live=s.status===\\\"fresh\\\"||s.status===\\\"stale\\\";\\n const phase=s.slots?\\\"Position cycle · \\\"+s.slots+\\\"/6 slots used\\\":s.setup?\\\"Waiting for retest\\\":\\\"Scanning for breakout\\\";\\n $(\\\"goldPaperState\\\").textContent=live?human(s.status)+\\\" quote · \\\"+time(s.quote)+\\\" · \\\"+phase+\\\" · Gold mark \\\"+fmt(s.mark):\\\"Shadow ledger \\\"+human(s.status||\\\"unavailable\\\");\\n const rows=live?Object.entries(s.books).map(([book,b])=>({...b,label:book===\\\"starter\\\"?\\\"Starter only\\\":\\\"Six slots\\\"})):[];\\n table(\\\"goldPaperBooks\\\",rows,[[\\\"Paper account\\\",r=>r.label],[\\\"Contracts (+ long / − short)\\\",r=>fmt(r.qty)],[\\\"Average entry\\\",r=>r.qty?fmt(r.avg):\\\"—\\\"],[\\\"Stop\\\",r=>r.qty?fmt(r.stop):\\\"—\\\"],[\\\"Cash P&L incl. fees (USD)\\\",r=>fmt(r.cash-10000)],[\\\"Closed\\\",r=>fmt(r.closed)]]);\\n table(\\\"goldPaperEvents\\\",s.events||[],[[\\\"Time\\\",r=>time(r.stamp)],[\\\"Event\\\",r=>human(r.kind)],[\\\"Account\\\",r=>r.book?human(r.book):\\\"Both\\\"],[\\\"Contracts\\\",r=>r.quantity==null?\\\"—\\\":fmt(r.quantity)],[\\\"Fill\\\",r=>r.price==null?\\\"—\\\":fmt(r.price)]]);\\n}\\nfunction render(){\"],[\"dashboard_static/app.js\",\" historyView(m);inspectorView(m);\",\" goldPaperView(m);historyView(m);inspectorView(m);\"]]")
UNIT = "recover-dashboard.service"
def ctl(*args):
    return subprocess.check_output(["systemctl", *args], text=True).strip()

def main():
    if os.geteuid():
        raise SystemExit("Run with sudo")
    proc=Path("/proc")/ctl("show",UNIT,"-p","MainPID","--value")
    args=(proc/"cmdline").read_bytes().decode().split("\0")
    if "recover_trading.dashboard" not in args:
        raise SystemExit("Unexpected dashboard command")
    base=(proc/"cwd").resolve()/"recover_trading"
    source=proc/"cwd"/"recover_trading"
    files={}
    for name,anchor,replacement in CHANGES:
        body=files.get(name)
        if body is None:
            body=(source/name).read_text()
        if replacement not in body:
            if body.count(anchor)!=1:
                raise SystemExit("Incompatible dashboard source: "+name)
            body=body.replace(anchor,replacement,1)
        files[name]=body
    compile(files["dashboard.py"],"dashboard.py","exec")
    stage=Path(tempfile.mkdtemp(prefix="gold-panel-",dir="/opt"))
    stage.chmod(0o755)
    lines=["[Service]"]
    for name,body in files.items():
        dest=stage/name
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(body)
        dest.chmod(0o644)
        lines.append(f"BindReadOnlyPaths={dest}:{base/name}")
    drop=Path("/etc/systemd/system")/(UNIT+".d")/"zzzzzzzz-gold-shadow-panel.conf"
    drop.parent.mkdir(exist_ok=True)
    old=drop.read_bytes() if drop.exists() else None
    pending=drop.with_suffix(".pending")
    pending.write_text("\n".join(lines)+"\n")
    pending.replace(drop)
    port=next((x.split("=",1)[1] for x in args if x.startswith("--port=")), "8765")
    if "--port" in args:
        port=args[args.index("--port")+1]
    try:
        ctl("daemon-reload")
        ctl("restart",UNIT)
        for attempt in range(8):
            try:
                with urlopen("http://127.0.0.1:"+port+"/api/overview",timeout=30) as res:
                    info=json.load(res)["gold_shadow"]
                print("Dashboard panel installed. Gold ledger status:",info["status"])
                return
            except (OSError,KeyError,ValueError):
                if attempt==7:
                    raise
                time.sleep(1)
    except Exception:
        if old is None:
            drop.unlink()
        else:
            drop.write_bytes(old)
        ctl("daemon-reload")
        ctl("restart",UNIT)
        raise

if __name__=="__main__":
    main()
