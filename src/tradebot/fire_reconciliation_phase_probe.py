"""M09 single-trade read-only financial evidence phase triage (DEMO only).

Diagnoses the first failure stage that the ordinary reconciliation currently
summarizes as broker_evidence_or_ledger_unavailable. Never saves financial
evidence, touches the original reconciliation ledger, sends orders, invokes
models, or claims trade release. Only Delta India DEMO GET calls are possible.

This is a diagnostic, not a substitute for immutable, reviewed reconciliation.
"""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import localcontext
import json
import os
from pathlib import Path
import re

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_bracket_evidence import _saved, BracketEvidenceError
from tradebot.fire_inventory import read_inventory, _read_rows, InventoryEvidenceError
from tradebot.fire_reconciliation import (
    ReconciliationError, analyse, identifier, normalize_fill,
    normalize_posting, timestamp_us, unique, EXTERNAL,
)

MAX_AGE = timedelta(days=7)
MIN_AGE = timedelta(minutes=10)
_REASON = re.compile(r"[a-z0-9_]{1,80}\Z")


def _safe_reason(exc, default):
    """Never publish remote API exceptions, broker payloads, or secrets."""
    if isinstance(exc, (ReconciliationError, BracketEvidenceError,
                        InventoryEvidenceError)):
        code = str(exc)
        if _REASON.fullmatch(code):
            return code
    return default



def _unattributed_wallet_hints(postings, fills, order_ids, product_id):
    """Classify ambiguous economic postings without returning broker identities.

    Mirrors only analyse()'s unattributed-posting predicate. This is a
    read-only clue, NOT attribution proof or permission to ignore postings.
    Values, timestamps, posting/order/fill IDs and account data stay private.
    """
    owned = set(order_ids)
    selected = [f for f in fills if f["order_id"] in owned]
    if not selected:
        return None
    first, last = selected[0]["at_us"], selected[-1]["at_us"]
    owned_fills = {f["id"] for f in selected}
    other_orders = {f["order_id"] for f in fills if f["order_id"] not in owned}
    other_fills = {f["id"] for f in fills if f["order_id"] not in owned}
    categories = []
    for p in postings:
        if p["type"] in EXTERNAL:
            continue
        oid, fid = p["order_id"], p["fill_id"]
        linked = oid in owned or fid in owned_fills
        within = first <= p["at_us"] <= last
        same_product = p["product_id"] == str(product_id)
        if linked or (same_product and within):
            continue
        if p["at_us"] < first or not (same_product or p["product_id"] is None):
            continue
        if (oid in other_orders or fid in other_fills) and not within:
            continue
        categories.append({
            "product_scope": "same_product" if same_product else "account_unscoped",
            "timing": "within_position" if within else "after_last_fill",
            "order_reference": "present" if oid is not None else "absent",
            "fill_reference": "present" if fid is not None else "absent",
            "posting_kind": p["type"] if p["type"] in
                            ("cashflow", "commission", "funding") else "other",
        })
    if not categories:
        return None
    return {"count": len(categories), "examples": categories[:5],
            "examples_truncated": len(categories) > 5}


def _base_report():
    return {
        "environment": "delta-india-demo",
        "mode": "authenticated_get_only_diagnostic",
        "status": "blocked",
        "stage": "preflight",
        "reason": "not_started",
        "stages_passed": [],
        "eligible_recent_btc_receipts": 0,
        "local_flat_btc_receipts": 0,
        "locally_unverified_bracket_receipts": 0,
        "authenticated_order_gets": 0,
        "fill_count": None,
        "wallet_posting_count": None,
        "financial_reconciliation_status": "awaiting_complete_broker_evidence",
        "is_net_realized_pnl": False,
        "funding_reconciled": False,
        "cashflow_and_commission_consistency_proven_in_memory": False,
        "unattributed_wallet_posting_diagnostic": None,
        "original_ledger_mutations": False,
        "temporary_ledger_mutations": False,
        "broker_order_mutations": False,
        "ai_calls": 0,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
    }


def probe_single_recent_btc(exchange, data_dir, *, now=None):
    """Select one recent locally-flat BTC FIRE and inspect GET phases in order."""
    out = _base_report()

    def block(stage, reason):
        out["stage"] = stage
        out["reason"] = reason
        return out

    if (getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        return block("preflight", "read_only_delta_demo_required")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return block("preflight", "trusted_utc_time_required")

    root = Path(data_dir)
    try:
        inventory = read_inventory(root, limit=200)
        if inventory["entries_truncated"]:
            return block("receipt_selection", "local_inventory_truncated")
        rows = _read_rows(
            root / "fire-ops.sqlite",
            "SELECT press,created_at,updated_at,status,result FROM fire_requests",
        )
        if rows is None:
            return block("receipt_selection", "original_btc_receipts_missing")
        by_id = {r[0]: r for r in rows}
    except InventoryEvidenceError as exc:
        return block("receipt_selection", _safe_reason(exc, "local_inventory_unavailable"))
    except Exception:
        return block("receipt_selection", "local_inventory_unavailable")

    btc = [item for item in inventory["entries"]
           if item["symbol"] == "BTCUSD"
           and item["category"] == "locally_reported_flat"]
    out["local_flat_btc_receipts"] = len(btc)
    selected = None
    for item in btc:
        if item["local_financial_report_present"]:
            continue
        try:
            t = datetime.fromisoformat(item["created_at"]).astimezone(timezone.utc)
            age = now.astimezone(timezone.utc) - t
        except (ValueError, TypeError, OverflowError):
            return block("receipt_selection", "invalid_receipt_timestamp")
        if not MIN_AGE < age < MAX_AGE:
            continue
        try:
            saved, fingerprint = _saved(root, "BTCUSD", item["fire_id"])
        except BracketEvidenceError:
            out["locally_unverified_bracket_receipts"] += 1
            continue
        out["eligible_recent_btc_receipts"] += 1
        if selected is None:
            selected = (item, saved, fingerprint)

    if selected is None:
        return block("receipt_selection", "no_recent_local_bracket_candidate")

    item, saved, fingerprint = selected
    row = by_id.get(item["fire_id"])
    if row is None:
        return block("receipt_selection", "original_btc_receipt_changed")
    try:
        payload = json.loads(row[4])
        if type(payload) is not dict:
            return block("receipt_selection", "original_btc_receipt_invalid")
        trade = dict(payload, id=item["fire_id"], created_at=row[1], status=row[3])
        start_us = timestamp_us(trade["created_at"])
        end_us = timestamp_us(now.astimezone(timezone.utc).isoformat())
        if not 0 < end_us - start_us < 7 * 86400 * 1_000_000:
            return block("receipt_selection", "bounded_history_window_invalid")
    except (ValueError, ReconciliationError, TypeError):
        return block("receipt_selection", "original_btc_receipt_invalid")
    out["stages_passed"].append("receipt_selection")

    try:
        response = exchange._request("GET", "/v2/products/BTCUSD")
        product = response["result"]
        if not isinstance(product, dict):
            return block("product", "broker_product_response_invalid")
        pid = product["id"]
        if type(pid) is not int or pid <= 0 or product.get("symbol") != "BTCUSD":
            return block("product", "broker_product_identity_mismatch")
    except Exception:
        return block("product", "broker_product_get_unavailable")
    out["stages_passed"].append("product")

    # Saved IDs are validated decimal strings by _saved before broker use.
    order_ids = [saved[k] for k in (
        "parent", "stop_loss_order", "take_profit_order")]
    orders = {}
    for order_id in order_ids:
        try:
            response = exchange._request(
                "GET", "/v2/orders/" + order_id, auth=True)
            row = response["result"]
            if not isinstance(row, dict) or str(row.get("id")) != order_id:
                return block("orders", "broker_order_identity_unverified")
            orders[order_id] = row
            out["authenticated_order_gets"] += 1
        except Exception:
            return block("orders", "broker_order_get_unavailable")
    out["stages_passed"].append("orders")

    try:
        raw_fills = exchange.product_fills(
            pid, start_time_us=start_us, end_time_us=end_us)
        if not isinstance(raw_fills, list):
            return block("fills", "broker_fill_window_unverified")
    except Exception:
        return block("fills", "broker_fill_history_unavailable")
    out["stages_passed"].append("fills")

    try:
        fills = unique([normalize_fill(row) for row in raw_fills])
    except Exception as exc:
        return block("fill_normalization", _safe_reason(
            exc, "broker_fill_schema_unverified"))
    out["fill_count"] = len(fills)
    out["stages_passed"].append("fill_normalization")

    try:
        raw_postings = exchange.wallet_postings(start_us, end_us)
        if not isinstance(raw_postings, list):
            return block("wallet_postings", "broker_wallet_window_unverified")
    except Exception:
        return block("wallet_postings", "broker_wallet_history_unavailable")
    out["stages_passed"].append("wallet_postings")

    try:
        postings = unique([normalize_posting(row) for row in raw_postings])
    except Exception as exc:
        return block("wallet_normalization", _safe_reason(
            exc, "broker_wallet_schema_unverified"))
    out["wallet_posting_count"] = len(postings)
    out["stages_passed"].append("wallet_normalization")

    try:
        with localcontext() as ctx:
            ctx.prec = 128
            result = analyse(
                "BTCUSD", trade, product, orders, fills, postings, start_us, end_us)
    except Exception as exc:
        reason = _safe_reason(exc, "financial_analysis_unverified")
        # The analyser emits this code only AFTER all broker cashflow and
        # commission postings match the signed fills, and BEFORE net P&L.
        # This is diagnostic-only, NOT a durable financial review.
        if isinstance(exc, ReconciliationError) and reason == "missing_broker_funding_total":
            out["cashflow_and_commission_consistency_proven_in_memory"] = True
        if isinstance(exc, ReconciliationError) and reason == "unattributed_wallet_posting":
            try:
                out["unattributed_wallet_posting_diagnostic"] = _unattributed_wallet_hints(
                    postings, fills, order_ids, pid)
            except Exception:
                # Never disclose broker data or change the original blocker if
                # the supplementary diagnostic itself cannot classify it.
                pass
        return block("financial_analysis", reason)
    out["cashflow_and_commission_consistency_proven_in_memory"] = True
    out["stages_passed"].append("financial_analysis")

    # A concurrent receipt rewrite/replacement cannot be treated as a clean
    # match, even though no original file was modified by this diagnostic.
    try:
        _, after = _saved(root, "BTCUSD", item["fire_id"])
        if after != fingerprint:
            return block("local_evidence_stability", "original_btc_receipt_changed")
    except Exception:
        return block("local_evidence_stability", "original_btc_receipt_unavailable")
    out["stages_passed"].append("local_evidence_stability")

    if result.get("is_net_realized_pnl") is not True:
        return block("financial_analysis", "broker_financial_evidence_unverified")

    out["status"] = "provisional_read_only_financial_analysis_complete"
    out["stage"] = "complete"
    out["reason"] = "not_persisted_not_current_trade_authority"
    # No money amounts, account IDs or immutable-source evidence are exported.
    # This is NOT the durable financial reconciliation release milestone.
    out["financial_reconciliation_status"] = "analysis_only_not_durable_report"
    out["funding_reconciled"] = True
    out["is_net_realized_pnl"] = False
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)
    exchange = DeltaDemo(
        api_key=os.environ.get("DELTA_DEMO_API_KEY", ""),
        api_secret=os.environ.get("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    result = probe_single_recent_btc(exchange, args.data_dir)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == (
        "provisional_read_only_financial_analysis_complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
