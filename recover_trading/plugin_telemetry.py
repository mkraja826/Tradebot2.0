"""Read-only, bounded telemetry for the Recover Trading MCP service."""
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

MARKETS = ("BTCUSD", "XAUTUSD")
ACTIONS = ("maintain", "repair_bracket", "update_bracket", "reduce", "close")
PROPOSAL_STATES = ("prepared", "requested", "proposed", "failed")
ATTEMPT_STATES = ("attempting", "verified", "terminal_no_fill", "outcome_unverified", "partial_result_unverified")
MODEL = re.compile(r"[A-Za-z0-9._-]{1,100}")
CODE = re.compile(r"[A-Za-z0-9_-]{1,100}")

def obj(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}

def tag(value, pattern=CODE):
    return value if isinstance(value, str) and pattern.fullmatch(value) else None

def integer(value):
    return value if type(value) is int and abs(value) <= 10**12 else None

def number(value):
    if type(value) in (int, float) and -10**12 <= value <= 10**12:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,15}(?:\.[0-9]{1,15})?", value):
        return value
    return None

def mapping(value):
    return value if isinstance(value, dict) else {}

def rows(path, sql, args):
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            return db.execute(sql,args).fetchall()
    except sqlite3.Error:
        return None

def report(symbol, root="/var/lib/recover-trading/demo", now=None):
    if symbol not in MARKETS:
        raise ValueError("unsupported market")
    now = int(time.time()) if now is None else now
    market = Path(root)/symbol
    try:
        heartbeat = obj((market/"status.json").read_text())
    except OSError:
        heartbeat = {}
    stamp = integer(heartbeat.get("timestamp"))
    age = now-stamp if stamp is not None and stamp <= now else None
    mg = mapping(heartbeat.get("management_execution"))
    proposals = rows(market/"orders.sqlite",
        "SELECT id,created,model,status,result FROM management_shadow WHERE symbol=? ORDER BY created DESC,id DESC LIMIT 20",
        (symbol,))
    attempts = rows(market/"orders.sqlite",
        "SELECT proposal_id,created,action,status,detail FROM management_attempts WHERE symbol=? ORDER BY created DESC,proposal_id DESC LIMIT 20",
        (symbol,))
    recent = []
    for ident, created, model, state, raw in proposals or []:
        d = obj(raw); p = mapping(d.get("proposal")); diag = mapping(d.get("diagnostics"))
        usage = mapping(diag.get("usage"))
        recent.append({"id":tag(ident),"created":integer(created),"model":tag(model,MODEL),
            "status":state if state in PROPOSAL_STATES else "unknown",
            "action":p.get("action") if p.get("action") in ACTIONS else None,
            "stop_loss":number(p.get("stop_loss")),"take_profit":number(p.get("take_profit")),
            "contracts":integer(p.get("contracts")),"error":tag(d.get("response_error") or d.get("error")),
            "elapsed_ms":integer(diag.get("elapsed_ms")),
            "usage":{k:integer(usage.get(k)) for k in ("prompt_tokens","completion_tokens","total_tokens")}})
    executed = []
    for ident, created, action, state, raw in attempts or []:
        d=obj(raw); p=mapping(d.get("plan")); receipt=mapping(d.get("receipt"))
        ev=d.get("evidence")
        executed.append({"proposal_id":tag(ident),"created":integer(created),
            "action":action if action in ACTIONS else None,
            "status":state if state in ATTEMPT_STATES else "unknown",
            "exchange_verified":state=="verified",
            "amended_leg":tag(d.get("amended_leg")),"observed_size":number(d.get("observed_size")),
            "before_size":number(p.get("before_size")),"expected_size":number(p.get("expected_size")),
            "stop_price":number(receipt.get("stop_price")),
            "evidence":tag(ev if isinstance(ev,str) else mapping(ev).get("status")),
            "last_reconciled":integer(d.get("last_reconciled"))})
    return {"symbol":symbol,"engine":"Recover Trading","execution_effect":"none",
        "heartbeat":{"timestamp":stamp,"age_seconds":age,"fresh":age is not None and age<=180,
            "entry_model":tag(heartbeat.get("entry_model"),MODEL),
            "management_model":tag(heartbeat.get("management_model"),MODEL),
            "status":tag(heartbeat.get("status")),
            "management_enabled":mg.get("enabled") if type(mg.get("enabled")) is bool else None,
            "management_status":tag(mg.get("status"))},
        "journal_status":"observed" if proposals is not None and attempts is not None else "incomplete",
        "recent_proposals":recent,"recent_attempts":executed,
        "limitations":["Heartbeat model configuration is not proof of a completed trade.",
            "Only journaled verified attempts count as recorded exchange verification.",
            "Recent records are bounded to 20 per category; absent records do not prove inactivity."]}
