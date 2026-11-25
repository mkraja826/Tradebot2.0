"""G25 weekend reopening evidence framework, isolated from live strategies."""
import argparse,json,re,sqlite3,time
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from contextlib import closing
from .performance import dec
from .gold_release_research import epoch
VERSION="gold-reopen-research-v1"
VENUE="CME_GLOBEX"
CALENDAR="https://www.cmegroup.com/trading-hours.html"
CHICAGO=ZoneInfo("America/Chicago")

def nominal_window(now):
    """Regular GC hours only, never a verified product holiday calendar."""
    local=datetime.fromtimestamp(now,CHICAGO)
    friday=local.date()-timedelta(days=(local.weekday()-4)%7)
    close=datetime.combine(friday,datetime.min.time(),CHICAGO).replace(hour=16)
    if close.timestamp()>now:close-=timedelta(days=7)
    reopen=close+timedelta(days=2,hours=1)
    return {"regular_close_utc":close.astimezone(timezone.utc).isoformat(),"regular_reopen_utc":reopen.astimezone(timezone.utc).isoformat(),
        "status":"nominal_only_holiday_exceptions_unverified","source_url":CALENDAR}

def normalize_calendar(raw,now):
    if raw.get("venue")!=VENUE or raw.get("product")!="GC" or raw.get("source_url")!=CALENDAR:raise ValueError("calendar_identity")
    c,o=epoch(raw.get("close_at")),epoch(raw.get("reopen_at"))
    contract=raw.get("contract")
    if not isinstance(contract,str) or not re.fullmatch(r"GC[FGHJKMNQUVXZ]20[0-9]{2}",contract):raise ValueError("contract")
    if c is None or o is None or not 24*3600<=o-c<=5*86400 or now>=c:raise ValueError("calendar_time")
    if datetime.fromtimestamp(c,CHICAGO).weekday()!=4 or datetime.fromtimestamp(o,CHICAGO).weekday() not in (6,0):raise ValueError("weekend_identity")
    return {"venue":VENUE,"product":"GC","contract":contract,"close_epoch":c,"reopen_epoch":o,
        "observed_epoch":now,"source_url":CALENDAR,"provenance":"operator_supplied_unverified"}

def normalize_trade(raw,now):
    if raw.get("venue")!=VENUE or raw.get("product")!="GC" or raw.get("currency")!="USD" or raw.get("unit")!="troy_ounce":raise ValueError("trade_identity")
    contract=raw.get("contract");t=epoch(raw.get("trade_at"));p=dec(raw.get("price"))
    if not isinstance(contract,str) or not re.fullmatch(r"GC[FGHJKMNQUVXZ]20[0-9]{2}",contract) or t is None or not 0<=now-t<=120 or p is None or p<=0:raise ValueError("trade_fields")
    src=raw.get("source_url")
    if not isinstance(src,str) or not src.startswith("https://") or len(src)>500:raise ValueError("source")
    return {"venue":VENUE,"product":"GC","contract":contract,"trade_epoch":t,"observed_epoch":now,"price":str(p),"source_url":src,"provenance":"operator_supplied_unverified"}

def compare(calendar,pre,post,now):
    out={"status":"insufficient_evidence","execution_effect":"none","direction":None}
    if not calendar or not pre or not post:return out
    if any(r.get(k)!=calendar.get(k) for r in (pre,post) for k in ("venue","product","contract")):return {**out,"status":"contract_mismatch"}
    c,o=calendar["close_epoch"],calendar["reopen_epoch"]
    a,b=pre["trade_epoch"],post["trade_epoch"]
    if not calendar["observed_epoch"]<c or not c-300<=a<c or not o<=b<=o+300 or not a<=pre["observed_epoch"]<=c or not b<=post["observed_epoch"]<=now:return {**out,"status":"window_mismatch"}
    p,q=dec(pre["price"]),dec(post["price"])
    if p is None or q is None or min(p,q)<=0:return out
    return {**out,"status":"operator_supplied_gap_unverified","observed_gap_bps":float((q/p-1)*10000),"contract":calendar["contract"],
        "pre_trade_epoch":a,"post_trade_epoch":b,"first_reopen_trade_verified":False,"last_preclose_trade_verified":False}

def database(root):
    db=sqlite3.connect(Path(root)/"reopen.sqlite",timeout=5)
    with db:db.execute("CREATE TABLE IF NOT EXISTS evidence (kind TEXT, observed_epoch INTEGER, payload TEXT, PRIMARY KEY(kind,observed_epoch))")
    return db

def report(root,now):
    out={"version":VERSION,"rule":"G25","execution_effect":"none","status":"research_only","nominal_window":nominal_window(now),
        "calendar_connection":"not_connected","licensed_trade_feed":"not_connected","indicative_spot_is_reopen_evidence":False}
    result={"status":"insufficient_evidence","execution_effect":"none","direction":None}
    try:
        with closing(sqlite3.connect((Path(root)/"reopen.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            rows=[(k,json.loads(r)) for k,r in db.execute("SELECT kind,payload FROM evidence WHERE observed_epoch<=? ORDER BY observed_epoch DESC",(now,))]
        cal=next((r for k,r in rows if k=="calendar"),None)
        if cal:
            matches=[r for k,r in rows if k=="trade" and r["contract"]==cal["contract"]]
            pre=max((r for r in matches if cal["close_epoch"]-300<=r["trade_epoch"]<cal["close_epoch"]),key=lambda r:r["trade_epoch"],default=None)
            post=min((r for r in matches if cal["reopen_epoch"]<=r["trade_epoch"]<=cal["reopen_epoch"]+300),key=lambda r:r["trade_epoch"],default=None)
            result=compare(cal,pre,post,now)
    except (sqlite3.Error,ValueError,KeyError,TypeError,ArithmeticError):pass
    out["comparison"]=result
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--directory",required=True);p.add_argument("--record-kind",choices=("calendar","trade"));p.add_argument("--input");a=p.parse_args();now=int(time.time())
    if a.record_kind:
        if not a.input:raise ValueError("input_required")
        raw=json.loads(Path(a.input).read_text())
        row=(normalize_calendar if a.record_kind=="calendar" else normalize_trade)(raw,now)
        with closing(database(a.directory)) as db,db:db.execute("INSERT INTO evidence VALUES (?,?,?)",(a.record_kind,now,json.dumps(row)))
    print(json.dumps(report(a.directory,now)))
if __name__=="__main__":main()
