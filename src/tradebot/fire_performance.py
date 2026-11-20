"""Read-only statistics from as-of-cutoff, broker-reconciled FIRE reports.

This is NOT a complete account performance report. Any unverified trade,
unsequenced report, or conflicting latest report remains outside the verified
sample. Later unverified evidence supersedes older successful snapshots.
No network calls, broker mutations, LLM requests or strategy modification.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

MARKETS = ("BTCUSD", "XAUTUSD")
RECONCILED = "broker_reconciled"


class PerformanceEvidenceError(ValueError):
    pass


def _decimal(value):
    if type(value) not in (str, int, Decimal):
        raise PerformanceEvidenceError("Invalid reported financial amount")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise PerformanceEvidenceError("Invalid reported financial amount") from None
    if not amount.is_finite() or len(amount.as_tuple().digits) > 36:
        raise PerformanceEvidenceError("Invalid reported financial amount")
    return amount


def _percent(n, d):
    return str((Decimal(n) * 100 / Decimal(d)).quantize(Decimal("0.01"))) if d else None


def _money(v):
    return str(v)


def _stats(records):
    """All numeric metrics describe the verified SUBSET, never whole-account P&L."""
    values = [row["pnl"] for row in sorted(records,
              key=lambda row: (row["exit_at_us"], row["key"]))]
    n = len(values)
    winning = [v for v in values if v > 0]
    losing = [v for v in values if v < 0]
    total = sum(values, Decimal(0))
    gross_win = sum(winning, Decimal(0))
    gross_loss = -sum(losing, Decimal(0))
    current = peak = worst_drawdown = Decimal(0)
    for pnl in values:
        current += pnl
        peak = max(peak, current)
        worst_drawdown = max(worst_drawdown, peak - current)
    return {
        "verified_trades": n,
        "wins": len(winning),
        "losses": len(losing),
        "breakeven": n - len(winning) - len(losing),
        "win_rate_pct": _percent(len(winning), n),
        "verified_subset_net_usd": _money(total) if n else None,
        "verified_subset_gross_profit_usd": _money(gross_win) if n else None,
        "verified_subset_gross_loss_usd": _money(gross_loss) if n else None,
        "verified_subset_expectancy_usd_per_trade": _money(total / n) if n else None,
        "verified_subset_profit_factor": _money(gross_win / gross_loss) if gross_loss else None,
        "verified_subset_trade_sequence_max_drawdown_usd": _money(worst_drawdown) if n else None,
        "profit_factor_note": "undefined_without_verified_losses" if not gross_loss else None,
        "sample_sufficiency": "insufficient_for_edge_claims" if n < 100 else "requires_independent_out_of_sample_validation",
    }


def _validated(report, key, cutoff):
    if (report.get("is_net_realized_pnl") is not True
            or report.get("financial_reconciliation_status") != RECONCILED
            or report.get("funding_reconciled") is not True
            or report.get("reconciliation_version") != "fire-reconciliation-v1"):
        return None
    start, stop = report.get("entry_at_us"), report.get("exit_at_us")
    if (type(start) is not int or type(stop) is not int
            or start <= 0 or not start < stop <= cutoff):
        return None
    fills, postings = report.get("matched_fill_ids"), report.get("matched_posting_ids")
    if (not isinstance(fills, list) or not fills
            or not isinstance(postings, list) or not postings
            or any(not isinstance(v, str) or not v for v in fills + postings)
            or len(set(fills)) != len(fills)
            or len(set(postings)) != len(postings)):
        return None
    try:
        net = _decimal(report.get("net_realized_pnl_usd"))
        gross = _decimal(report.get("gross_realized_pnl_usd"))
        fees = _decimal(report.get("reconciled_fees_usd"))
        funding = _decimal(report.get("funding_cashflow_usd"))
    except PerformanceEvidenceError:
        return None
    if gross - fees + funding != net:
        return None
    return dict(key=key, exit_at_us=stop, pnl=net,
                fill_ids=fills, posting_ids=postings)


def read_performance(database):
    """Read immutable reconciliation snapshots; never refresh from the broker.

    Reports can be historical and later corrected. The last AS-OF report per
    trade wins; a latest tie with conflicting payloads is always unverified.
    Any unsequenced report means latest evidence cannot be established.
    """
    path = Path(database)
    empty = dict(source="local_reconciliation_reports_only",
                 as_of_scope="historical_snapshots_not_live_broker_state",
                 is_account_realized_pnl=False, is_account_drawdown=False,
                 total_reviewed_trades=0, unverified_trades=0,
                 unverified_reasons={}, last_reconciliation_as_of_us=None,
                 **_stats([]), by_market={market: _stats([]) for market in MARKETS})
    if not path.exists():
        return dict(empty, evidence_status="ledger_missing")
    if not path.is_file() or path.is_symlink():
        raise PerformanceEvidenceError("Untrusted reconciliation database")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",
                                     uri=True,timeout=10)) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute("SELECT trade_key,body FROM reports").fetchall()
    except sqlite3.Error as exc:
        raise PerformanceEvidenceError("Reconciliation reports unavailable") from None
    grouped = defaultdict(list)
    for key, body in rows:
        if (not isinstance(key,str) or key.count(":") != 1
                or key.split(":")[0] not in MARKETS or not key.split(":")[1]):
            raise PerformanceEvidenceError("Malformed reconciliation ownership")
        try:
            report = json.loads(body)
        except (json.JSONDecodeError,TypeError):
            raise PerformanceEvidenceError("Malformed reconciliation report") from None
        if not isinstance(report, dict):
            raise PerformanceEvidenceError("Malformed reconciliation report")
        grouped[key].append(report)
    verified = []
    reasons = Counter()
    latest_cutoff = None
    for key, reports in grouped.items():
        timestamps = [r.get("reconciliation_as_of_us") for r in reports]
        if any(type(x) is not int or x <= 0 for x in timestamps):
            reasons["unsequenced_or_unverified_report"] += 1
            continue
        last = max(timestamps)
        latest_cutoff = max(latest_cutoff or last, last)
        newest = [r for r in reports if r["reconciliation_as_of_us"] == last]
        if len({json.dumps(r,sort_keys=True,separators=(",",":")) for r in newest}) > 1:
            reasons["conflicting_latest_reports"] += 1
            continue
        report = newest[0]
        valid = _validated(report, key, last)
        if valid is None:
            reasons[str(report.get("reconciliation_reason") or
                        "unverified_or_inconsistent_report")[:64]] += 1
            continue
        verified.append(valid)
    # A shared broker fill/posting ID must never inflate two trade totals.
    owned = {}
    for entry in verified:
        for kind, ids in (("fill",entry["fill_ids"]),("posting",entry["posting_ids"])):
            for id_ in ids:
                owner_key = (kind,id_)
                if owner_key in owned and owned[owner_key] != entry["key"]:
                    raise PerformanceEvidenceError("Broker evidence attributed to multiple trades")
                owned[owner_key] = entry["key"]
    by_market = {market: _stats([x for x in verified if x["key"].startswith(market+":")])
                 for market in MARKETS}
    return {
        **empty,
        **_stats(verified),
        "by_market":by_market,
        "evidence_status":"historical_verification_snapshots",
        "total_reviewed_trades":len(grouped),
        "unverified_trades":len(grouped)-len(verified),
        "unverified_reasons":dict(sorted(reasons.items())),
        "last_reconciliation_as_of_us":latest_cutoff,
        "all_reviewed_trades_verified":len(grouped)>0 and len(grouped)==len(verified),
        "coverage_warning":"Do not extrapolate to unreviewed trades or account P&L",
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database",default="data/fire-reconciliation.sqlite")
    options=parser.parse_args(argv)
    try:
        report=read_performance(options.database)
    except PerformanceEvidenceError as exc:
        print(json.dumps({"status":"unavailable","reason":str(exc),
                          "is_account_realized_pnl":False}))
        return 2
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
