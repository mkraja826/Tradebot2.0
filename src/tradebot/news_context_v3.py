"""Official release metadata; no forecast inference or historical vintage reconstruction."""
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET
from urllib.parse import urlsplit
import re
URLS={"cpi_release":"https://www.bls.gov/feed/cpi.rss",
      "nfp_release":"https://www.bls.gov/feed/empsit.rss",
      "fomc_release":"https://www.federalreserve.gov/feeds/press_monetary.xml"}
ATOM="{http://www.w3.org/2005/Atom}"

def parse(raw,key,now):
    if len(raw)>1000000 or "<!DOCTYPE" in raw.upper() or "<!ENTITY" in raw.upper(): raise ValueError("unsafe_feed")
    root=ET.fromstring(raw); entries=[]
    if key=="fomc_release":
        for x in root.findall(".//item"):
            if x.findtext("title")!="Federal Reserve issues FOMC statement": continue
            link=x.findtext("link","")
            if not re.fullmatch(r"https://www.federalreserve.gov/newsevents/pressreleases/monetary[0-9]{8}[a-z]\.htm",link): continue
            t=parsedate_to_datetime(x.findtext("pubDate"))
            if t.tzinfo is None or t>now: continue
            entries.append({"source":"federal_reserve_monetary_rss","url":link,"published_at":t.astimezone(timezone.utc).isoformat(),"event":"fomc_statement"})
        if not entries: raise ValueError("no_statement")
        return max(entries,key=lambda x:x["published_at"])
    stem="cpi" if key=="cpi_release" else "empsit"
    if key not in ("cpi_release","nfp_release") or root.findtext(ATOM+"id")!="bls.gov:feed:"+stem: raise ValueError("wrong_feed")
    for x in root.findall(ATOM+"entry"):
        link=x.find(ATOM+"link"); link=link.get("href","") if link is not None else ""
        if not re.fullmatch(r"https://www.bls.gov/news.release/archives/"+stem+r"_[0-9]{8}\.htm",link): continue
        t=datetime.fromisoformat(x.findtext(ATOM+"published"))
        if t.tzinfo is None or t>now: continue
        body=" ".join(x.findtext(ATOM+"content","").split())
        entries.append({"source":"bls_official_atom","url":link,"feed_timestamp":t.astimezone(timezone.utc).isoformat(),
            "title":x.findtext(ATOM+"title","")[:300],"summary":body[:1000],
            "release_time_verified":False,"consensus":None})
    if not entries: raise ValueError("no_release")
    return max(entries,key=lambda x:x["feed_timestamp"])

def fomc_active(item,*,now,closed_at,frame_seconds):
    try:
        if item["status"]!="ready" or not 0<=now-item["observed_at"]<=420: return None
        d=item["data"]
        if d["source"]!="federal_reserve_monetary_rss" or d["event"]!="fomc_statement": return None
        stamp=datetime.fromisoformat(d["published_at"])
        if stamp.tzinfo is None: return None
        t=stamp.timestamp()
        if t>item["observed_at"]: return None
        return int(0<=now-t<=2700 and t<=closed_at-frame_seconds and closed_at<=now)
    except (ValueError,KeyError,TypeError,AttributeError): return None
