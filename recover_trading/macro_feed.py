"""Published daily/weekly Gold context, never fabricated intraday values."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
import gzip
from tradebot.gold_macro_v3 import history, features as macro_features
from tradebot.gold_stress_v3 import parse as stress_parse, features as stress_features
from tradebot.news_context_v3 import parse as news_parse, fomc_active, URLS as NEWS

SERIES = {"broad_dollar": "DTWEXBGS", "yields": "DGS10,DFII10",
          "market_vix": "VIXCLS", "financial_stress": "STLFSI4"}
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="


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


def collect_context(*, reader=fetch):
    def one(key):
        try:
            today=datetime.now(timezone.utc)
            url=(FRED+SERIES[key]+"&cosd="+(today.date()-timedelta(days=45)).isoformat()
                 if key in SERIES else NEWS[key])
            raw=reader(url)
            now=datetime.now(timezone.utc)
            result={"status":"ready","observed_at":now.timestamp()}
            if key in ("broad_dollar","yields"):
                result["macro_history"]={"source":"fred_daily_as_observed","series":history(raw,key,now)}
            elif key in SERIES:
                result["data"]=stress_parse(raw,key,now)
            else:
                result["data"]=news_parse(raw,key,now)
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
