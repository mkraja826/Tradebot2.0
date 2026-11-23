"""Read-only BTCUSD DEMO post-trade loss diagnostics from reconciled evidence.

This is an accounting-contribution and hypothesis-triage report, NOT a
causal explanation, broker statement, trading signal or strategy optimizer.
It cannot contact the broker, spend GPT/Kimi credits, or authorize orders.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3

from tradebot.fire_performance import _decimal, _validated


class LossDiagnosticError(ValueError):
    pass


def _readonly(path):
    file = Path(path)
    if not file.is_file() or file.is_symlink():
        raise LossDiagnosticError("immutable_local_evidence_unavailable")
    try:
        db = sqlite3.connect(file.absolute().as_uri() + "?mode=ro", uri=True,
                             timeout=5)
        db.execute("PRAGMA query_only=ON")
        return db
    except sqlite3.Error:
        raise LossDiagnosticError("immutable_local_evidence_unavailable") from None


def accounting_contributor(gross, fees, funding, net):
    """Only classify verified arithmetic components, not WHY the market moved."""
    if net >= 0:
        return "not_a_net_loss"
    if gross < 0:
        return "negative_gross_price_pnl"
    if gross - fees < 0:
        return "fees_overwhelmed_nonnegative_gross"
    if gross - fees + funding < 0:
        return "funding_reversed_nonnegative_after_fee_pnl"
    return "unclassified_accounting_loss"


def _tier(metadata):
    if not isinstance(metadata, dict):
        return "unknown"
    data = metadata.get("sizing_evidence")
    if not isinstance(data, dict):
        return "unrecorded"
    tier = data.get("tier")
    return tier if tier in ("exploratory_one", "medium_two", "strong_three") else "unknown"


def _summary(entries):
    total = sum((r["net"] for r in entries), Decimal(0))
    wins = sum(r["net"] > 0 for r in entries)
    losses = sum(r["net"] < 0 for r in entries)
    return {
        "verified_trades": len(entries),
        "wins": wins,
        "losses": losses,
        "breakeven": len(entries) - wins - losses,
        "verified_subset_net_usd": str(total) if entries else None,
        "verified_subset_mean_net_usd": str(total / len(entries)) if entries else None,
        "verified_win_rate_pct": str(
            (Decimal(wins) * 100 / Decimal(len(entries))).quantize(
                Decimal("0.01"))) if entries else None,
        "sample_sufficient_for_strategy_change": False,
    }


def analyze(financial_database, fire_database, *, max_reports=4000,
            recent_limit=30):
    """Audit only latest as-of, broker-reconciled BTCUSD closed trade reports.

    Reject conflicting latest revisions and reused broker fill/posting IDs.
    The FIRE ledger is contextual metadata; unverified metadata never
    changes accounting results or constitutes evidence of trade causality.
    """
    if (type(max_reports) is not int or not 1 <= max_reports <= 10000
            or type(recent_limit) is not int or not 1 <= recent_limit <= 100):
        raise LossDiagnosticError("invalid_report_limits")
    answer = {
        "mode": "local_read_only_reconciled_loss_diagnostics",
        "market": "BTCUSD", "environment": "delta-india-demo",
        "status": "awaiting_broker_reconciled_trades",
        "account_pnl_verified": False, "broker_mutations": False,
        "ai_calls": 0,
        "scope": "historical_verified_subset_only",
        "loss_accounting_contributors": {},
        "unverified_report_reasons": {},
        "metadata_coverage": {
            "matched_fire_receipts": 0,
            "missing_or_ambiguous_fire_receipts": 0,
        },
        "by_tier": {}, "by_direction": {},
        "verified_statistics": _summary([]),
        "recent_verified_trade_summaries": [],
        "interpretation": (
            "Price PnL, fees and funding are accounting contributions. They "
            "do not establish whether an entry, indicator or exit rule was wrong."
        ),
        "next_research_step": (
            "Compare both wins and losses by size/direction with matched "
            "pre-entry signals, stop/target and execution timing; validate "
            "hypotheses out of sample before changing GPT-6 policy."
        ),
    }
    if not Path(financial_database).exists():
        answer["status"] = "financial_reconciliation_ledger_missing"
        return answer
    with closing(_readonly(financial_database)) as db:
        try:
            rows = db.execute(
                "SELECT trade_key,body FROM reports ORDER BY trade_key"
            ).fetchmany(max_reports + 1)
        except sqlite3.Error:
            raise LossDiagnosticError("financial_reports_unavailable") from None
    if len(rows) > max_reports:
        raise LossDiagnosticError("financial_report_cap_exceeded")
    grouped = defaultdict(list)
    unknown = Counter()
    for key, body in rows:
        if not isinstance(key, str) or not key.startswith("BTCUSD:"):
            continue
        press = key[len("BTCUSD:"):]
        if not re.fullmatch(r"[0-9a-f]{32}", press):
            unknown["untrusted_trade_reference"] += 1
            continue
        try:
            report = json.loads(body)
        except (TypeError, ValueError):
            unknown["malformed_report"] += 1
            continue
        if not isinstance(report, dict):
            unknown["malformed_report"] += 1
            continue
        grouped[key].append(report)

    verified, duplicate_ids = [], {}
    for key, history in grouped.items():
        asofs = [r.get("reconciliation_as_of_us") for r in history]
        if any(type(v) is not int or v <= 0 for v in asofs):
            unknown["unsequenced_report"] += 1
            continue
        latest = max(asofs)
        copies = [r for r in history if r["reconciliation_as_of_us"] == latest]
        if len({json.dumps(r, sort_keys=True, separators=(",", ":"))
                for r in copies}) != 1:
            unknown["conflicting_latest_report"] += 1
            continue
        report = copies[0]
        existing = _validated(report, key, latest)
        if existing is None:
            unknown["not_fully_broker_reconciled"] += 1
            continue
        gross = _decimal(report["gross_realized_pnl_usd"])
        fees = _decimal(report["reconciled_fees_usd"])
        funding = _decimal(report["funding_cashflow_usd"])
        net = _decimal(report["net_realized_pnl_usd"])
        row = dict(
            key=key, press=key.split(":", 1)[1],
            net=net, gross=gross, fees=fees, funding=funding,
            exit_at_us=existing["exit_at_us"],
            duration_seconds=(existing["exit_at_us"] - report["entry_at_us"]) / 1_000_000,
            accountant=accounting_contributor(gross, fees, funding, net),
            fill_ids=existing["fill_ids"], posting_ids=existing["posting_ids"],
        )
        verified.append(row)
        for kind, values in (
            ("fill", row["fill_ids"]), ("posting", row["posting_ids"])):
            for value in values:
                duplicate_ids.setdefault((kind, value), set()).add(key)

    conflicted = {
        owner for owners in duplicate_ids.values() if len(owners) > 1
        for owner in owners
    }
    if conflicted:
        unknown["shared_broker_evidence"] += len(conflicted)
        verified = [r for r in verified if r["key"] not in conflicted]

    metadata = {}
    if Path(fire_database).exists():
        with closing(_readonly(fire_database)) as db:
            try:
                records = db.execute(
                    "SELECT press,status,result FROM fire_requests"
                ).fetchmany(max_reports + 1)
            except sqlite3.Error:
                raise LossDiagnosticError("fire_receipts_unavailable") from None
        if len(records) > max_reports:
            raise LossDiagnosticError("fire_receipt_cap_exceeded")
        for press, status, raw in records:
            if type(press) is not str or not re.fullmatch("[0-9a-f]{32}", press):
                continue
            try:
                value = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if type(value) is dict and status == "flat_verified" and value.get("orders_submitted") is True:
                metadata[press] = value

    by_tier = defaultdict(list)
    by_direction = defaultdict(list)
    contributors = Counter()
    summaries = []
    for row in sorted(verified, key=lambda x: (x["exit_at_us"], x["key"])):
        info = metadata.get(row["press"])
        if info is None:
            answer["metadata_coverage"]["missing_or_ambiguous_fire_receipts"] += 1
        else:
            answer["metadata_coverage"]["matched_fire_receipts"] += 1
        tier = _tier(info)
        direction = (info.get("direction") if info is not None else None)
        direction = direction if direction in ("LONG", "SHORT") else "unknown"
        by_tier[tier].append(row)
        by_direction[direction].append(row)
        if row["net"] < 0:
            contributors[row["accountant"]] += 1
        summaries.append({
            "fire_id": row["press"],
            "outcome": "loss" if row["net"] < 0 else "win" if row["net"] > 0 else "breakeven",
            "net_realized_pnl_usd": str(row["net"]),
            "gross_realized_pnl_usd": str(row["gross"]),
            "reconciled_fees_usd": str(row["fees"]),
            "funding_cashflow_usd": str(row["funding"]),
            "accounting_contributor": row["accountant"],
            "direction": direction,
            "tier": tier,
            "contracts_recorded": (
                info.get("contracts") if info and type(info.get("contracts")) is int
                else None),
            "duration_seconds": row["duration_seconds"],
        })

    answer.update(
        status=("verified_trades_available" if verified
                else "awaiting_broker_reconciled_trades"),
        verified_statistics=_summary(verified),
        loss_accounting_contributors=dict(sorted(contributors.items())),
        unverified_report_reasons=dict(sorted(unknown.items())),
        by_tier={k: _summary(v) for k,v in sorted(by_tier.items())},
        by_direction={k: _summary(v) for k,v in sorted(by_direction.items())},
        recent_verified_trade_summaries=summaries[-recent_limit:],
    )
    return answer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--financial-database",
                        default="data/fire-reconciliation.sqlite")
    parser.add_argument("--fire-database", default="data/fire-ops.sqlite")
    args = parser.parse_args(argv)
    try:
        report = analyze(args.financial_database, args.fire_database)
    except LossDiagnosticError as exc:
        print(json.dumps({
            "status": "unavailable", "reason_code": str(exc),
            "broker_mutations": False, "ai_calls": 0,
            "account_pnl_verified": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
