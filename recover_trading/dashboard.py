"""Local, read-only dashboard for Recover Trading journals."""
import argparse
import json
import math
import sqlite3
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .performance import read_performance
from .strategy_evidence import report as strategy_evidence_report
from .regime_performance import report as regime_performance
from .combination_intelligence import report as combination_intelligence
from .overlap_confidence import report as overlap_confidence
from .overlap_forward import report as overlap_forward
from .deferred_overview import report as deferred_overview
from .trade_excursion import report as excursion_report
from .open_excursion import report as open_excursion_report
from .exit_context import geometry as exit_geometry
from .target_amendment_preview import inspect as target_preview
from .decision_review import read_review
from .decision_quality import report as decision_quality
from .execution_cost import report as execution_cost
from .exit_cost_preview import build as exit_cost_preview
from .chart_overlay import build as chart_overlay
from .chart_studies import studies as chart_studies
from .strategy_lab import build as strategy_lab
from .performance_analytics import build as performance_analytics
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
    from .kimi_review import read as read_kimi_review
    kimi=read_kimi_review(root.parent.parent/"kimi-review",symbol)
    costs=execution_cost(root,symbol,performance,review,int(time.time()))
    cost_preview=exit_cost_preview(position_preview,costs)
    overlay=chart_overlay(symbol,latest,position_preview,cost_preview,[decode(f["detail"]) for f in fills or []],mgr,int(time.time()))
    strategy_report=strategy_evidence_report(root,symbol,performance)
    deferred_report=deferred_overview(root.parent,symbol,int(time.time()))
    lab=strategy_lab(symbol,heartbeat,strategy_report,deferred_report,int(time.time()))
    return {"symbol":symbol,"decision_quality":quality,"execution_cost":costs,"exit_cost_preview":cost_preview,"chart_overlay":overlay,"outcome_learning":learning,"kimi_review":kimi,"learning_memory":learning_memory(symbol,learning,quality),"memory_comparison":memory_comparison(root.parent.parent/"memory-comparison",symbol),"exit_geometry":exit_context,"target_amendment_preview":target_preview(latest,symbol,int(time.time())),"performance":performance,"performance_analytics":performance_analytics(performance,excursions,int(time.time())),"strategy_evidence":strategy_report,"strategy_lab":lab,"regime_performance":regime_performance(root,symbol,performance),"combination_intelligence":combination_intelligence(root,symbol),"overlap_confidence":overlap_confidence(root,symbol),"overlap_forward":overlap_forward(root.parent.parent/"overlap-forward",symbol),"deferred_research":deferred_report,"trade_excursions":excursions,"open_excursion":ox,"position_preview":position_preview,"management_shadow":management,"management_lifecycle":management_lifecycle,"management_attempts":management_attempts,"management_report":mgr,"postfill_bracket":postfill,"bracket_contract":repair_status(latest,symbol,int(time.time())),"management_compat":management_audit(root,symbol,int(time.time())),"submission_audit":submission,"historical_submission_evidence":historical_submission_report(root,symbol),"decision_review":review,"forward_validation":forward_report(root,symbol),"dual_market":dual_report(root,symbol),"reference_strategy":reference_strategy_report(root,symbol),"paired_forward":paired_forward_report(root,symbol),"planner_comparison":planner_comparison_report(root,symbol),"signal_research":research,"heartbeat":heartbeat,"snapshot":latest,"wallet_history":history,
            "decisions":decision_rows,"orders":entries,"fills":[decode(f["detail"]) for f in fills] if fills is not None else None,
            "prices":points,"order_counts":counts,"decision_counts":dc,
            "availability":{"decisions":proposals is not None,"orders":entries is not None,
                            "positions":isinstance(latest,dict) and "positions" in latest,
                            "wallets":isinstance(latest,dict) and "wallets" in latest},
            "win_rate":None,"realized_trade_pnl":None}

CHART_FRAMES={"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400}
def chart_data(root,symbol,frame,now,cache_dir=None):
    if symbol not in MARKETS or frame not in CHART_FRAMES:
        raise ValueError("Unknown chart selection")
    step=CHART_FRAMES[frame]
    rows=query(Path(root)/symbol/"market.sqlite",
        "SELECT stamp,payload FROM samples WHERE symbol=? AND series=? AND stamp<=? ORDER BY stamp DESC LIMIT 350",
        (symbol,"candle:"+frame,now-step))
    candles=[];invalid=0
    for row in reversed(rows or []):
        t=row["stamp"];p=decode(row["payload"])
        if not isinstance(p,dict) or type(t) is not int or t%step or p.get("time")!=t:
            invalid+=1;continue
        o,h,l,c,v=(p.get(k) for k in ("open","high","low","close","volume"))
        if not all(type(x) in (int,float) and math.isfinite(x) for x in (o,h,l,c,v)) or not 0<l<=min(o,c)<=max(o,c)<=h or v<0:
            invalid+=1;continue
        candles.append({"time":t,"open":o,"high":h,"low":l,"close":c,"volume":v})
    source="demo_archived_completed_candles"
    observed_at=None
    from .chart_feed import read_cache
    cached=read_cache(cache_dir,symbol,frame,now)
    if cached and (not candles or cached["candles"][-1]["time"]>=candles[-1]["time"]):
        candles=cached["candles"];invalid=cached["invalid_rows"];source=cached["source"];observed_at=cached["observed_at"]
    gaps=sum(b["time"]-a["time"]!=step for a,b in zip(candles,candles[1:]))
    return {"symbol":symbol,"frame":frame,"step":step,"source":source,"observed_at":observed_at,"generated":now,
        "status":"observed" if candles else "unavailable" if rows is None else "empty",
        "candles":candles,"studies":chart_studies(candles,step),"invalid_rows":invalid,"gap_count":gaps,
        "last_close_age_s":now-candles[-1]["time"]-step if candles else None}

def reference_chart(symbol,frame,now,reference_dir):
    from .chart_feed import read_cache,REFERENCE_SOURCE
    if symbol not in MARKETS or frame not in CHART_FRAMES:
        raise ValueError("Unknown chart selection")
    step=CHART_FRAMES[frame]
    p=read_cache(reference_dir,symbol,frame,now,source=REFERENCE_SOURCE)
    candles=p["candles"] if p else []
    return {"symbol":symbol,"frame":frame,"step":step,"source":REFERENCE_SOURCE,
        "generated":now,"observed_at":p["observed_at"] if p else None,
        "status":"observed" if candles else "unavailable","candles":candles,
        "studies":chart_studies(candles,step),"invalid_rows":p["invalid_rows"] if p else 0,
        "gap_count":sum(b["time"]-a["time"]!=step for a,b in zip(candles,candles[1:])),
        "last_close_age_s":now-candles[-1]["time"]-step if candles else None}

def handler(root,cache_dir=None,reference_dir=None):
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
                      "/market-chart.js":("market-chart.js","text/javascript; charset=utf-8"),
                      "/vendor/lightweight-charts.js":("vendor/lightweight-charts.js","text/javascript; charset=utf-8"),
                      "/vendor/LICENSE":("vendor/LICENSE","text/plain; charset=utf-8"),
                      "/vendor/NOTICE":("vendor/NOTICE","text/plain; charset=utf-8"),
                      "/style.css":("style.css","text/css; charset=utf-8")}
            if path in assets:
                name,mime = assets[path]
                try: content=(STATIC/name).read_bytes()
                except FileNotFoundError: return self.send(503,b"Dashboard asset unavailable","text/plain")
                return self.send(200,content,mime)
            if path == "/api/chart":
                try:
                    q=parse_qs(urlsplit(self.path).query,strict_parsing=True,max_num_fields=3)
                    if set(q) not in ({"symbol","frame"},{"symbol","frame","source"}) or any(len(v)!=1 for v in q.values()):raise ValueError("Invalid query")
                    source=q.get("source",["demo"])[0]
                    if source not in ("demo","reference"):raise ValueError("Invalid source")
                    data=reference_chart(q["symbol"][0],q["frame"][0],int(time.time()),reference_dir) if source=="reference" else chart_data(root,q["symbol"][0],q["frame"][0],int(time.time()),cache_dir)
                except ValueError:
                    return self.send(400,b"Invalid chart selection","text/plain")
                return self.send(200,json.dumps(data,allow_nan=False).encode(),"application/json")
            if path == "/api/chart-quote":
                try:
                    q=parse_qs(urlsplit(self.path).query,strict_parsing=True,max_num_fields=2)
                    if set(q) not in ({"symbol"},{"symbol","source"}) or any(len(v)!=1 for v in q.values()) or q["symbol"][0] not in MARKETS:raise ValueError("Invalid symbol")
                    from .chart_quote import read_quote,REFERENCE_SOURCE
                    source=q.get("source",["demo"])[0]
                    if source not in ("demo","reference"):raise ValueError("Invalid source")
                    data=read_quote(reference_dir,q["symbol"][0],int(time.time()),source=REFERENCE_SOURCE) if source=="reference" else read_quote(cache_dir,q["symbol"][0],int(time.time()))
                except ValueError:
                    return self.send(400,b"Invalid chart quote selection","text/plain")
                return self.send(200,json.dumps(data,allow_nan=False).encode(),"application/json")
            if path == "/api/overview":
                data={"generated":int(time.time()),"markets":[report(root,s) for s in MARKETS]}
                return self.send(200,json.dumps(data,allow_nan=False).encode(),"application/json")
            return self.send(404,b"Not found","text/plain")
    return Handler

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir",default="data/recover-service")
    p.add_argument("--port",type=int,default=8765)
    p.add_argument("--chart-cache-dir",default=None)
    p.add_argument("--reference-cache-dir",default=None)
    args=p.parse_args()
    with ThreadingHTTPServer(("127.0.0.1",args.port),handler(args.data_dir,args.chart_cache_dir,args.reference_cache_dir)) as server:
        print(f"Local dashboard: http://127.0.0.1:{server.server_port}",flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__=="__main__":
    main()
