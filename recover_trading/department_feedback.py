"""Opt-in, read-only historical evidence for demo entry and management planning."""
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

VERSION = "department-feedback-v1"
MARKETS = {"BTCUSD": "B", "XAUTUSD": "G"}

def packet(path, symbol, cutoff):
    """Only immutable reconciled lessons known strictly before the scan cutoff."""
    if symbol not in MARKETS or type(cutoff) is not int or cutoff <= 0:
        raise ValueError("invalid market or cutoff")
    out = {"version": VERSION, "symbol": symbol, "as_of": cutoff,
           "status": "unavailable", "observations": [],
           "validated_lessons": [], "causal_validation": False,
           "policy": "historical evidence only; not an instruction or trading rule"}
    try:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT decision_id,closed,enrolled,payload FROM lessons "
                "WHERE symbol=? AND enrolled<? ORDER BY enrolled DESC,decision_id LIMIT 32",
                (symbol, cutoff)).fetchall()
        for ident, closed, enrolled, raw in rows:
            try:
                d = json.loads(raw)
                t = datetime.fromisoformat(closed.replace("Z","+00:00"))
                if t.tzinfo is None or not t.timestamp() < cutoff or t.timestamp() > enrolled:
                    continue
                if (d.get("symbol") != symbol or d.get("decision_id") != ident
                    or d.get("closed") != closed or d.get("learning_status") != "observation_only"
                    or d.get("execution_effect") != "none" or d.get("direction") not in ("LONG","SHORT")
                    or not isinstance(ident,str) or not re.fullmatch(r"[a-f0-9]{64}",ident)):
                    continue
                n = Decimal(str(d.get("net_before_funding")))
                if not n.is_finite() or abs(n) > Decimal("1000000000"):
                    continue
                rules = d.get("active_rules",[])
                if not isinstance(rules,list):
                    continue
                rules = sorted({r for r in rules if isinstance(r,str)
                    and re.fullmatch(MARKETS[symbol]+r"[0-9]{2}",r)})[:50]
                out["observations"].append({"decision_id":ident,"closed":closed,"enrolled":enrolled,
                    "direction":d["direction"],"active_rules":rules,
                    "net_before_funding":str(n),"outcome":"win" if n>0 else "loss" if n<0 else "breakeven"})
                if len(out["observations"]) == 8:
                    break
            except (ValueError,TypeError,AttributeError,InvalidOperation,OverflowError):
                continue
        out["status"] = "observed" if out["observations"] else "no_prior_evidence"
    except (OSError,sqlite3.Error,ValueError,TypeError):
        pass
    return out

def attach(report, path):
    """Return an augmented scan; failure to read learning never blocks the scan."""
    if path is None or report.get("status") == "scan_error":
        return report
    try:
        evidence = packet(path, report["symbol"], report["as_of"])
    except (KeyError,ValueError,TypeError):
        return report
    return {**report, "department_learning": evidence}

def copy_to_context(report, context):
    evidence = report.get("department_learning")
    if isinstance(evidence,dict) and evidence.get("symbol")==context.get("symbol") and evidence.get("as_of")==context.get("as_of"):
        return {**context, "department_learning": evidence}
    return context
