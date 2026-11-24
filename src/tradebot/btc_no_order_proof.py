"""Reproduce a known BTC isolated pre-order 1:1 rejection from immutable proof.

No broker calls, orders, account aggregation, risk bypass, or mutable state.
"""
from decimal import Decimal as D, InvalidOperation
import json
import sqlite3


def proved_gross_distance_failure(db, press, receipt):
    if (receipt.get("risk_rejection_detail") != "stop_distance_exceeds_target"
            or receipt.get("reason_code") != "risk_governor_failed"
            or receipt.get("orders_submitted") is not False
            or receipt.get("protection_verified") is not False
            or receipt.get("broker_order_id") or receipt.get("exit_order_ids")
            or receipt.get("selected_leverage") != 20
            or type(receipt.get("contracts")) is not int
            or receipt["contracts"] < 1):
        return False
    try:
        row=db.execute("SELECT snapshot FROM fire_model_inputs WHERE press=?",
                       (press,)).fetchone()
        if row is None:
            return False
        snap=json.loads(row[0])
        scope=snap.get("fire_execution_scope")
        core=snap.get("core")
        quote=receipt.get("decision_quote")
        diag=receipt.get("risk_quote_diagnostics")
        if (snap.get("environment")!="delta-india-demo"
                or type(scope) is not dict
                or scope.get("unattended_demo_mode") is not True
                or type(core) is not dict or type(quote) is not dict
                or quote!={k:core.get(k) for k in ("best_bid","best_ask")}
                or type(diag) is not dict
                or diag.get("source")!="snapshot_vs_signed_broker_quote"
                or receipt.get("direction") not in ("LONG","SHORT")):
            return False
        long=receipt["direction"]=="LONG"
        entry=D(str(quote["best_ask" if long else "best_bid"]))
        broker=D(str(diag["broker_entry"]))
        model=D(str(diag["model_entry"]))
        sl=D(str(receipt["stop_loss"]))
        tp=D(str(receipt["take_profit"]))
        if (not all(x.is_finite() and x>0 for x in (entry,broker,model,sl,tp))
                or entry!=model
                or not ((sl<entry<tp and sl<broker<tp) if long
                        else (tp<entry<sl and tp<broker<sl))):
            return False
        for price,name in ((entry,"model"),(broker,"broker")):
            v=diag.get(name)
            if type(v) is not dict:
                return False
            stop=abs(price-sl);target=abs(tp-price)
            satisfies=target>=stop
            # The AI's quote may pass 1:1 while the fresh broker quote fails.
            # Either model state is acceptable ONLY with matching arithmetic;
            # the final signed broker quote MUST fail.
            if (stop<=0 or target<=0
                    or v.get("gross_1_to_1_satisfied") is not satisfies
                    or (name=="broker" and satisfies)
                    or D(str(v["stop_distance"]))!=stop
                    or D(str(v["target_distance"]))!=target):
                return False
            if abs(D(str(v["gross_reward_risk"]))-target/stop)>D("1e-20"):
                return False
        # Signed quote drift: the broker can move above OR below the AI quote.
        drift=(broker-entry)/entry*D(10000)
        return abs(D(str(diag["quote_change_bps"]))-drift)<=D("1e-18")
    except (sqlite3.Error,ValueError,TypeError,KeyError,InvalidOperation,
            ArithmeticError,ZeroDivisionError):
        return False
