"""Private owner declaration of main/isolated Delta DEMO mode, not broker proof."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import stat
from tradebot.delta import DEMO_API

def read_manual_mode(exchange, path=None, now=None):
    """A matched owner declaration NEVER authorizes trades or validates margin."""
    result = {"status":"not_configured","account":"main",
              "declared_mode":None,"broker_margin_verified":False,
              "trade_authorized":False,"safe_to_enable_fire":False}
    try:
        if exchange.base_url != DEMO_API or exchange.allow_orders is not False:
            return result
        p = Path(path) if path else Path.home()/".config/tradebot2/manual-account-mode.json"
        if p.is_symlink() or not p.is_file():
            return result
        fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o600
                    or st.st_uid!=os.geteuid() or st.st_size>1024):
                return result
            data = os.read(fd, 1025)
        finally:
            os.close(fd)
        if len(data)>1024:
            return result
        obj = json.loads(data)
        if (type(obj) is not dict or set(obj)!={"schema","environment","account",
                "mode","declared_at"} or type(obj["schema"]) is not int
                or obj["schema"]!=1 or obj["environment"]!="delta-india-demo"
                or obj["account"]!="main" or obj["mode"]!="isolated"):
            return result
        ts = datetime.fromisoformat(obj["declared_at"])
        instant = now or datetime.now(timezone.utc)
        if ts.tzinfo is None or instant.tzinfo is None:
            return result
        if not 0<=(instant-ts).total_seconds()<=30*86400:
            result["status"]="owner_declaration_expired"
            return result
        result["status"]="owner_declared_not_broker_verified"
        result["declared_mode"]="isolated"
    except Exception:
        pass
    return result
