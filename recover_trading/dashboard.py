"""Local, read-only dashboard for Recover Trading journals."""
import argparse
import json
import sqlite3
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .performance import read_performance
from .strategy_evidence import report as strategy_evidence_report
from .regime_performance import report as regime_performance
from .deferred_overview import report as deferred_overview
from .trade_excursion import report as excursion_report
from .open_excursion import report as open_excursion_report
from .exit_context import geometry as exit_geometry
from .target_amendment_preview import inspect as target_preview
from .decision_review import read_review
from .decision_quality import report as decision_quality
from .outcome_learning import report as outcome_learning
from .learning_memory import build as learning_memory
from .memory_comparison import report as memory_comparison
from .submission_audit import read_audit
from .historical_submission_evidence import report as historical_submission_report
from .position_preview import observe
from .bracket_contract import repair_status
from .management_lifecycle import audit as management_lifecycle_audit
from .management_report import report as management_report
from .postfill_bracket import audit as postfill_audit
from .management_compat import audit as management_audit

MARKETS = ("BTCUSD", "XAUTUSD")
STATIC = Path(__file__).with_name("dashboard_static")

def query(path, sql, args=()):
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, args)]
    except sqlite3.OperationalError:
        return None

def decode(value):
    try:
        return json.loads(value) if value is not None else None
    except (ValueError, TypeError):
        return None

def forward_report(root,symbol):
    try:
        result=decode((root/"forward_validation.json").read_text(encoding="utf-8"))
        if isinstance(result,dict) and result.get("symbol")==symbol and result.get("version")=="forward-reference-v1":
            return result
    except OSError:
        pass
    return None

def dual_report(root,symbol):
    try:
        result=decode((root/"dual_market.json").read_text(encoding="utf-8"))
        if isinstance(result,dict) and result.get("symbol")==symbol and result.get("version")=="dual-market-v1":
            return result
    except OSError:
        pass
    return None

def reference_strategy_report(root,symbol):
    try:
        result=decode((root/"reference_strategy.json").read_text(encoding="utf-8"))
        if isinstance(result,dict) and result.get("symbol")==symbol and result.get("version")=="reference-strategy-v1":
            return result
    except OSError:
        pass
    return None

def paired_forward_report(root,symbol):
    try:
        result=decode((root/"paired_forward.json").read_text(encoding="utf-8"))
        if isinstance(result,dict) and result.get("symbol")==symbol and result.get("version")=="paired-forward-v1":
            return result
    except OSError:
        pass
    return None

def planner_comparison_report(root,symbol):
    try:
        result=decode((root/"planner_comparison.json").read_text(encoding="utf-8"))
        if isinstance(result,dict) and result.get("symbol")==symbol and result.get("version")=="planner-comparison-v1":
            return result
    except OSError:
        pass
    return None

def report(root, symbol):
    if symbol not in MARKETS:
        raise ValueError("Unknown market")
    root = Path(root) / symbol
    orders, decisions, market = (root / p for p in ("orders.sqlite","decisions.sqlite","market.sqlite"))
    try:
        heartbeat = decode((root/"status.json").read_text(encoding="utf-8"))
    except OSError:
        heartbeat = None
    snapshots = query(orders, "SELECT observed,detail FROM lifecycle_snapshots WHERE symbol=? ORDER BY id DESC LIMIT 120", (symbol,))
    latest = decode(snapshots[0]["detail"]) if snapshots else None
    history = []
    for s in reversed(snapshots or []):
        data = decode(s["detail"])
        if isinstance(data, dict) and "wallets" in data:
            history.append({"observed":s["observed"],"wallets":data["wallets"]})
    proposals = query(decisions, "SELECT id,model,status,created,result,context FROM decisions WHERE symbol=? ORDER BY created DESC,rowid DESC LIMIT 40", (symbol,))
    decision_rows = []
    for d in proposals or []:
        context = decode(d.pop("context")) or {}
        d["result"] = decode(d["result"])
        d["direction_engine"] = context.get("direction_engine")
        d["signals"] = [{k:s.get(k) for k in ("id","direction","frame")} for s in context.get("new_signals",[])]
        decision_rows.append(d)
    entries = query(orders, "SELECT client_id,status,intent FROM orders WHERE symbol=? ORDER BY rowid DESC LIMIT 50", (symbol,))
    observed = query(orders, "SELECT client_id,observed,detail FROM observed_orders WHERE symbol=?",(symbol,))
    by_id = {o["client_id"]:decode(o["detail"]) for o in observed or []}
    for e in entries or []:
        e["intent"] = decode(e["intent"])
        e["exchange"] = by_id.get(e["client_id"])
    fills = query(orders, "SELECT detail FROM observed_fills WHERE symbol=? ORDER BY rowid DESC LIMIT 50",(symbol,))
    candles = query(market, "SELECT stamp,payload FROM samples WHERE symbol=? AND series='candle:5m' ORDER BY stamp DESC LIMIT 120",(symbol,))
    points = []
    for c in reversed(candles or []):
        p = decode(c["payload"])
        if isinstance(p,dict):
            points.append({"time":c["stamp"],"close":p.get("close")})
    counts = query(orders,"SELECT status,count(*) AS count FROM orders WHERE symbol=? GROUP BY status",(symbol,))
    dc = query(decisions,"SELECT status,count(*) AS count FROM decisions WHERE symbol=? GROUP BY status",(symbol,))
    research=query(root/"signal_research.sqlite", """SELECT rule_id,family,regime,horizon_s,
          count(*) AS samples, sum(status=\'observed\') AS observed, sum(status=\'pending\') AS pending,
          sum(status=\'missed\') AS missed,
          sum(CASE WHEN return_bps>0 THEN 1 ELSE 0 END) AS positive,
          round(avg(return_bps),3) AS avg_mark_return_bps
          FROM observations WHERE symbol=? GROUP BY rule_id,family,regime,horizon_s
          ORDER BY rule_id,regime,horizon_s""",(symbol,))
    management_rows=query(orders,"SELECT id,bucket,created,status,result FROM management_shadow WHERE symbol=? ORDER BY bucket DESC LIMIT 20",(symbol,))
    management_evaluated=query(orders,"SELECT id,context,result FROM management_shadow WHERE symbol=? AND status='proposed' ORDER BY created DESC LIMIT 1",(symbol,))
    management_lifecycle=management_lifecycle_audit(management_evaluated,latest,int(time.time()))
    management_attempts=query(orders,"SELECT proposal_id,created,action,status FROM management_attempts WHERE symbol=? ORDER BY created DESC LIMIT 20",(symbol,))
    management_counts=query(orders,"SELECT status,count(*) AS count FROM management_shadow WHERE symbol=? GROUP BY status",(symbol,))
    management={"status":"prepared_only","execution_effect":"none","counts":management_counts,"recent":[{**r,"result":decode(r["result"])} for r in management_rows or []]}
    performance=read_performance(root,symbol)
    unresolved=sum(x["count"] for x in counts if x["status"] in ("submitting","unknown")) if counts is not None else None
    position_preview=observe(latest,symbol,int(time.time()),unresolved)
    receipts=query(orders,"SELECT detail FROM orders WHERE symbol=? AND status='acknowledged'",(symbol,))
    postfill=postfill_audit(latest,symbol,int(time.time()),[decode(r["detail"]) for r in receipts or []],[decode(r["detail"]) for r in fills or [] if isinstance(decode(r["detail"]),dict)])
    ox=open_excursion_report(root,symbol,latest,int(time.time()))
    raw_pos=latest["positions"][0] if isinstance(latest,dict) and isinstance(latest.get("positions"),list) and len(latest["positions"])==1 else None
    exit_context=exit_geometry({"entry_price":position_preview.get("entry_price"),"mark_price":position_preview.get("mark_price"),"size":position_preview.get("size"),"legs":position_preview.get("legs"),"bracket_state":position_preview.get("bracket_state")},ox,raw_pos,((heartbeat or {}).get("direction_engine") or {}).get("direction"))
    review=read_review(root,symbol,performance)
    excursions=excursion_report(root,symbol,performance)
    submission=read_audit(root,symbol)
    mgr=management_report(root,symbol,heartbeat)
    quality=decision_quality(review,performance,excursions,submission,mgr)
    learning=outcome_learning(root.parent.parent/"outcome-learning",symbol)
    return {"symbol":symbol,"decision_quality":quality,"outcome_learning":learning,"learning_memory":learning_memory(symbol,learning,quality),"memory_comparison":memory_comparison(root.parent.parent/"memory-comparison",symbol),"exit_geometry":exit_context,"target_amendment_preview":target_preview(latest,symbol,int(time.time())),"performance":performance,"strategy_evidence":strategy_evidence_report(root,symbol,performance),"regime_performance":regime_performance(root,symbol,performance),"deferred_research":deferred_overview(root.parent,symbol,int(time.time())),"trade_excursions":excursions,"open_excursion":ox,"position_preview":position_preview,"management_shadow":management,"management_lifecycle":management_lifecycle,"management_attempts":management_attempts,"management_report":mgr,"postfill_bracket":postfill,"bracket_contract":repair_status(latest,symbol,int(time.time())),"management_compat":management_audit(root,symbol,int(time.time())),"submission_audit":submission,"historical_submission_evidence":historical_submission_report(root,symbol),"decision_review":review,"forward_validation":forward_report(root,symbol),"dual_market":dual_report(root,symbol),"reference_strategy":reference_strategy_report(root,symbol),"paired_forward":paired_forward_report(root,symbol),"planner_comparison":planner_comparison_report(root,symbol),"signal_research":research,"heartbeat":heartbeat,"snapshot":latest,"wallet_history":history,
            "decisions":decision_rows,"orders":entries,"fills":[decode(f["detail"]) for f in fills] if fills is not None else None,
            "prices":points,"order_counts":counts,"decision_counts":dc,
            "availability":{"decisions":proposals is not None,"orders":entries is not None,
                            "positions":isinstance(latest,dict) and "positions" in latest,
                            "wallets":isinstance(latest,dict) and "wallets" in latest},
            "win_rate":None,"realized_trade_pnl":None}

def handler(root):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, content, mime):
            self.send_response(status)
            self.send_header("Content-Type",mime)
            self.send_header("Content-Length",str(len(content)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)
        def do_GET(self):
            # Prevent DNS-rebinding access to the unauthenticated loopback dashboard.
            host = self.headers.get("Host","")
            if host not in (f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"):
                return self.send(403,b"Forbidden","text/plain")
            path = urlsplit(self.path).path
            assets = {"/":("index.html","text/html; charset=utf-8"),
                      "/app.js":("app.js","text/javascript; charset=utf-8"),
                      "/style.css":("style.css","text/css; charset=utf-8")}
            if path in assets:
                name,mime = assets[path]
                return self.send(200,(STATIC/name).read_bytes(),mime)
            if path == "/api/overview":
                data={"generated":int(time.time()),"markets":[report(root,s) for s in MARKETS]}
                return self.send(200,json.dumps(data,allow_nan=False).encode(),"application/json")
            return self.send(404,b"Not found","text/plain")
    return Handler

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir",default="data/recover-service")
    p.add_argument("--port",type=int,default=8765)
    args=p.parse_args()
    with ThreadingHTTPServer(("127.0.0.1",args.port),handler(args.data_dir)) as server:
        print(f"Local dashboard: http://127.0.0.1:{server.server_port}",flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__=="__main__":
    main()
