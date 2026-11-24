"""Offline parser for a documented external liquidation message.
External market data is not Delta demo liquidation evidence.
No connection, authentication, execution or strategy activation.
"""
from decimal import Decimal,InvalidOperation
from tradebot.opportunity_journal_v3 import digest

def positive(value):
    if type(value) not in (int,str): raise ValueError("invalid_decimal")
    try: x=Decimal(value)
    except InvalidOperation: raise ValueError("invalid_decimal") from None
    if not x.is_finite() or x<=0 or abs(x.adjusted())>12 or len(x.as_tuple().digits)>30:
        raise ValueError("invalid_decimal")
    return x

def parse_external_batch(message,*,received_ms):
    if type(received_ms) is not int or received_ms<=0: raise ValueError("invalid_receipt_time")
    if not isinstance(message,dict) or message.get("topic")!="allLiquidation.BTCUSDT" or message.get("type")!="snapshot":
        raise ValueError("wrong_channel")
    stamp=message.get("ts")
    if type(stamp) is not int or not 0<=received_ms-stamp<=10000: raise ValueError("stale_message")
    rows=message.get("data")
    if not isinstance(rows,list) or not 1<=len(rows)<=5000: raise ValueError("invalid_batch")
    result=[]
    for row in rows:
        if not isinstance(row,dict) or row.get("s")!="BTCUSDT": raise ValueError("wrong_instrument")
        t=row.get("T")
        if type(t) is not int or not 0<=stamp-t<=10000: raise ValueError("invalid_event_time")
        side=row.get("S")
        if side not in ("Buy","Sell"): raise ValueError("unknown_position_side")
        size=positive(row.get("v")); price=positive(row.get("p"))
        result.append({"liquidated_position_side":"LONG" if side=="Buy" else "SHORT",
                       "event_ms":t,"size_raw":str(size),"bankruptcy_price":str(price)})
    return {"source":"bybit_mainnet_btcusdt_public_liquidation","provider_symbol":"BTCUSDT",
            "received_ms":received_ms,"published_ms":stamp,"message_sha256":digest(message),
            "events":result,"coverage_complete":False,"delta_demo_evidence":False,
            "strategy_activation_authorized":False}

def evidence_readiness(*,delta_has_liquidation_flag,external_http_status):
    return {"mode":"liquidation_source_research","delta_public_trade_liquidation_flag":delta_has_liquidation_flag is True,
            "external_public_http_status":external_http_status,
            "external_stream_verified":False,"continuous_coverage_verified":False,
            "strategies":{"B17":"deferred","B18":"deferred"},
            "reason":"market_wide_directional_liquidation_coverage_not_verified",
            "execution_authorized":False,"orders_submitted":0,"paid_ai_requests":0}
