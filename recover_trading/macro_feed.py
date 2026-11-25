"""Published daily/weekly Gold context, never fabricated intraday values."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
import gzip
import csv,io
from math import isfinite
from tradebot.gold_macro_v3 import history, features as macro_features
from tradebot.gold_stress_v3 import parse as stress_parse, features as stress_features
from tradebot.news_context_v3 import parse as news_parse, fomc_active, URLS as NEWS

SERIES = {"broad_dollar": "DTWEXBGS", "yields": "DGS10,DFII10",
          "market_vix": "VIXCLS", "financial_stress": "STLFSI4"}
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
ALFRED = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id="
ALFRED_SOURCE = "alfred_same_day_vintage_as_observed"


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "RecoverTrading research/1.0",
                                       "Accept-Encoding": "identity"}), timeout=5) as r:
        raw = r.read(1_000_001)
    if len(raw)>1_000_000:
        raise ValueError("oversize")
    if raw.startswith(b"\x1f\x8b"):
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
            raw=f.read(1_000_001)
    if len(raw)>1_000_000:
        raise ValueError("oversize")
    return raw.decode("utf-8-sig")


def alfred_csv(key,today,reader):
    """Single-series same-day vintage with exact header; no cross-series imputation."""
    ids=SERIES[key].split(",")
    vintage=today.date().isoformat();suffix=today.strftime("%Y%m%d")
    observations={}
    for ident in ids:
        raw=reader(ALFRED+ident+"&cosd="+(today.date()-timedelta(days=45)).isoformat()+"&vintage_date="+vintage)
        rows=csv.DictReader(io.StringIO(raw));field=ident+"_"+suffix
        if rows.fieldnames!=["observation_date",field]:raise ValueError("unexpected_vintage_or_series")
        values={}
        for r in rows:
            if None in r:raise ValueError("malformed_csv")
            day=datetime.strptime(r["observation_date"],"%Y-%m-%d").date()
            if day>=today.date():continue
            value=r[field]
            if value in ("",".",None):continue
            v=float(value)
            if not isfinite(v):raise ValueError("invalid_value")
            if day in values and values[day]!=v:raise ValueError("conflicting_observation")
            values[day]=v
        observations[ident]=values
    days=sorted(set().union(*(set(v) for v in observations.values())))
    output=io.StringIO();w=csv.writer(output,lineterminator="\n")
    w.writerow(["observation_date",*ids])
    for day in days:w.writerow([day.isoformat(),*(observations[i].get(day,"") for i in ids)])
    return output.getvalue()

def collect_context(*, reader=fetch):
    def one(key):
        try:
            today=datetime.now(timezone.utc)
            url=(FRED+SERIES[key]+"&cosd="+(today.date()-timedelta(days=45)).isoformat()
                 if key in SERIES else NEWS[key])
            source=None
            if key in SERIES:
                try:
                    raw=alfred_csv(key,today,reader);source=ALFRED_SOURCE
                except Exception:
                    raw=reader(url)
            else:raw=reader(url)
            now=datetime.now(timezone.utc)
            if source and now.date()!=today.date():raise ValueError("vintage_day_changed")
            result={"status":"ready","observed_at":now.timestamp()}
            if key in ("broad_dollar","yields"):
                result["macro_history"]={"source":source or "fred_daily_as_observed","series":history(raw,key,now)}
            elif key in SERIES:
                result["data"]=stress_parse(raw,key,now)
                if source:result["data"]["source"]=source
            else:
                result["data"]=news_parse(raw,key,now)
            if source:result["vintage_date"]=today.date().isoformat()
            if key in SERIES:result["source"]=source or "fred_as_observed"
            return key,result
        except Exception as exc:
            return key,{"status":"unavailable","reason":type(exc).__name__}
    with ThreadPoolExecutor(max_workers=5) as pool:
        return dict(pool.map(one, (*SERIES, "fomc_release")))


def apply_context(snapshot, refs, now):
    m=snapshot["markets"]["XAUTUSD"]
    m["context"].update(macro_features(refs,observed_at=now))
    m["context"].update(stress_features(refs,observed_at=now))
    item=m["frames"].get("15m",{})
    if item.get("status")=="ready":
        item["fomc_post_statement"]=fomc_active(refs.get("fomc_release",{}),now=now,
                                               closed_at=item["closed_at"],frame_seconds=900)
