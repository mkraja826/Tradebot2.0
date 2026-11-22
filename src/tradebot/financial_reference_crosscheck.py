"""Diagnostic-only account-wide fill crosscheck for conflicting wallet refs."""
from tradebot.fire_reconciliation import normalize_fill, unique


def crosscheck_foreign_fill_refs(exchange, postings, fills, order_ids,
                                 product_id, start_us, end_us):
    """Signed GET only. Never changes attribution or grants trade permission."""
    report = {
        "status": "unverified",
        "external_signed_fill_history_consistent": False,
        "overlap_reference_count": 0,
        "matched_other_product_fills": 0,
        "matched_same_product_other_orders": 0,
        "matched_selected_order_missing_filtered_fill": 0,
        "reference_not_found_in_signed_history": 0,
        "financial_attribution_verified": False,
        "safe_to_enable_fire": False,
        "broker_order_mutations": False,
    }
    try:
        owned = set(order_ids)
        selected = [f for f in fills if f["order_id"] in owned]
        if not selected:
            return report
        start = min(f["at_us"] for f in selected)
        end = max(f["at_us"] for f in selected)
        known = {f["id"]: f for f in fills}
        if len(known) != len(fills):
            return report
        targets = set()
        for p in postings:
            if (p["product_id"] == str(product_id)
                    and start <= p["at_us"] <= end
                    and p["type"] in ("commission", "cashflow", "funding")
                    and p["order_id"] not in owned
                    and p["fill_id"] not in {f["id"] for f in selected}
                    and p["fill_id"] is not None):
                targets.add(p["fill_id"])
        report["overlap_reference_count"] = len(targets)
        if not targets:
            return report
        rows = exchange._account_history(
            "/v2/fills", start_us, end_us)
        if type(rows) is not list:
            return report
        all_fills = unique([normalize_fill(row) for row in rows])
        full = {f["id"]: f for f in all_fills}
        if len(full) != len(all_fills):
            return report
        if any(k not in full or full[k] != v for k, v in known.items()):
            report["status"] = "filtered_unfiltered_fill_conflict"
            return report
        report["external_signed_fill_history_consistent"] = True
        for ref in targets:
            f = full.get(ref)
            if f is None:
                report["reference_not_found_in_signed_history"] += 1
            elif f["product_id"] != str(product_id):
                report["matched_other_product_fills"] += 1
            elif f["order_id"] in owned:
                report["matched_selected_order_missing_filtered_fill"] += 1
            else:
                report["matched_same_product_other_orders"] += 1
        report["status"] = "diagnostic_only_unresolved"
    except Exception:
        report["status"] = "signed_fill_crosscheck_unavailable"
    return report
