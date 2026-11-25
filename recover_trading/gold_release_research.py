"""Point-in-time economic event research. No AI or trading interfaces."""
import argparse,json,re,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
from contextlib import closing
from .performance import dec
from .macro_feed import fetch
from tradebot.news_context_v3 import parse,URLS
VERSION="gold-release-research-v1"
SPECS={"G20":("cpi_release","cpi_mom_sa_pct","cpi"),"G21":("nfp_release","nonfarm_payroll_change_thousands","empsit")}

def epoch(value):
    try:
        t=datetime.fromisoformat(value.replace("Z","+00:00"))
        return int(t.timestamp()) if t.tzinfo is not None else None
    except (ValueError,TypeError,AttributeError,OverflowError):return None

def normalize(record,kind,now):
    if not isinstance(record,dict) or kind not in ("forecast","actual"):raise ValueError("record")
    rule=record.get("rule");spec=SPECS.get(rule)
    if not spec or record.get("measure")!=spec[1]:raise ValueError("measure")
    month=record.get("reference_month")
    if not isinstance(month,str) or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])",month):raise ValueError("reference_month")
    release=epoch(record.get("release_at"));v=dec(record.get("value"))
    if release is None or v is None or abs(v)>100000 or type(now) is not int:raise ValueError("value_or_release")
    if kind=="forecast" and now>=release:raise ValueError("late_forecast")
    if kind=="actual" and now<release:raise ValueError("early_actual")
    if rule=="G21" and v!=v.to_integral_value():raise ValueError("payroll_units")
    source=record.get("source_url")
    if not isinstance(source,str) or not source.startswith("https://") or len(source)>500:raise ValueError("source")
    if kind=="actual":
        expected=datetime.fromtimestamp(release,timezone.utc).strftime("%m%d%Y")
        if source!="https://www.bls.gov/news.release/archives/"+spec[2]+"_"+expected+".htm":raise ValueError("official_archive_required")
    return {"rule":rule,"measure":spec[1],"reference_month":month,"release_epoch":release,"value":str(v),"kind":kind,
            "source_url":source,"observed_epoch":now,"provenance":"operator_supplied_unverified"}

def evaluate(forecast,actual,now):
    out={"status":"insufficient_evidence","execution_effect":"none","surprise":None}
    if not forecast or not actual:return out
    if any(forecast.get(k)!=actual.get(k) for k in ("rule","measure","reference_month","release_epoch")):
        return {**out,"status":"event_identity_mismatch"}
    t=actual["release_epoch"]
    if not forecast["observed_epoch"]<t<=actual["observed_epoch"]<=now:return {**out,"status":"timestamp_mismatch"}
    delta=dec(actual["value"])-dec(forecast["value"])
    # Only measure surprise, not gold direction. Inflation/interest-rate
    # responses depend on regime, and unverified inputs cannot signal.
    return {**out,"status":"paired_operator_evidence_unverified","rule":actual["rule"],"surprise":str(delta),
            "measure":actual["measure"],"reference_month":actual["reference_month"],
            "observed_after_release_s":actual["observed_epoch"]-t,"direction":None}

def probe(reader=fetch,clock=time.time):
    out={"version":VERSION,"execution_effect":"none","status":"research_only","sources":{}}
    for rule,(key,measure,stem) in SPECS.items():
        try:
            raw=reader(URLS[key]);now=datetime.fromtimestamp(clock(),timezone.utc)
            result=parse(raw,key,now)
            out["sources"][rule]={"status":"official_metadata_observed","data":result,"measure":measure,"consensus_status":"not_connected"}
        except Exception as e:
            out["sources"][rule]={"status":"source_unavailable","error":type(e).__name__,"http_status":getattr(e,"code",None),"consensus_status":"not_connected"}
    return out

def database(root):
    db=sqlite3.connect(Path(root)/"economic.sqlite",timeout=5)
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS evidence (rule TEXT, month TEXT, release_epoch INTEGER, kind TEXT, observed_epoch INTEGER, payload TEXT, PRIMARY KEY(rule,month,release_epoch,kind,observed_epoch))")
        db.execute("CREATE TABLE IF NOT EXISTS probes (observed_epoch INTEGER PRIMARY KEY,payload TEXT NOT NULL)")
    return db

def record(root,kind,raw,now):
    row=normalize(raw,kind,now)
    with closing(database(root)) as db,db:
        db.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?)",(row["rule"],row["reference_month"],row["release_epoch"],kind,now,json.dumps(row)))
    return row

def report(root,now):
    out={"version":VERSION,"status":"research_only","execution_effect":"none","rules":[]}
    try:
        with closing(sqlite3.connect((Path(root)/"economic.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            for rule in SPECS:
                rows=[json.loads(r) for r, in db.execute("SELECT payload FROM evidence WHERE rule=? AND observed_epoch<=? ORDER BY observed_epoch DESC",(rule,now))]
                actual=next((r for r in rows if r["kind"]=="actual"),None)
                forecast=next((r for r in rows if r["kind"]=="forecast" and actual and all(r[k]==actual[k] for k in ("reference_month","release_epoch","measure"))),None)
                out["rules"].append({"id":rule,**evaluate(forecast,actual,now)})
            p=db.execute("SELECT observed_epoch,payload FROM probes ORDER BY observed_epoch DESC LIMIT 1").fetchone()
            if p:out.update(last_probe_epoch=p[0],feed_probe=json.loads(p[1]))
    except (sqlite3.Error,ValueError,KeyError,TypeError,ArithmeticError):out["status"]="journal_unavailable"
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--directory",required=True);p.add_argument("--probe",action="store_true");p.add_argument("--record-kind",choices=("forecast","actual"));p.add_argument("--input");a=p.parse_args();now=int(time.time())
    if a.probe:
        r=probe()
        with closing(database(a.directory)) as db,db:db.execute("INSERT OR IGNORE INTO probes VALUES (?,?)",(now,json.dumps(r)))
    if a.record_kind:
        if not a.input:raise ValueError("input_required")
        record(a.directory,a.record_kind,json.loads(Path(a.input).read_text()),now)
    print(json.dumps(report(a.directory,int(time.time()))))
if __name__=="__main__":main()
