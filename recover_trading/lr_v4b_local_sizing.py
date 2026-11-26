"""Deterministic BTC demo sizing; no provider calls."""
from decimal import Decimal, ROUND_FLOOR
from .performance import dec

FRACTION = Decimal("0.20")
LEVERAGE = Decimal(20)
FEE_ROOM = Decimal("0.0015")  # modeled round-trip cost reserve, not actual fee schedule


def local_sizing(signal, account):
    if signal.get("symbol")!="BTCUSD" or signal.get("version")!="lr-v4b" or signal.get("side") not in ("buy","sell"):
        raise ValueError("invalid LR signal")
    p=account["product"]
    asset=(p.get("settling_asset") or {}).get("symbol")
    quote_asset=(p.get("quoting_asset") or {}).get("symbol")
    if (p.get("symbol")!="BTCUSD" or p.get("notional_type")!="vanilla"
            or p.get("contract_unit_currency")!="BTC" or not asset or asset!=quote_asset):
        raise ValueError("unsupported contract units")
    wallets=[w for w in account["wallets"] if w.get("asset_symbol")==asset]
    if len(wallets)!=1:
        raise ValueError("settlement wallet identity unverified")
    balance=dec(wallets[0].get("balance"))
    available=dec(wallets[0].get("available_balance"))
    if balance is None or available is None or balance<=0 or available<0:
        raise ValueError("invalid settlement wallet balance")
    q=account.get("decision_quote") or {}
    price=dec(q.get("best_ask" if signal["side"]=="buy" else "best_bid"))
    value=dec(p.get("contract_value"))
    if q.get("status")!="fresh_book" or price is None or price<=0 or value is None or value<=0:
        raise ValueError("invalid contract or executable quote")
    unit=price*value
    budget=balance*FRACTION
    size=int((budget*LEVERAGE/unit).to_integral_value(rounding=ROUND_FLOOR))
    margin=unit*size/LEVERAGE
    fee_room=unit*size*FEE_ROOM
    detail={"method":"local_20pct","capital_basis":"flat_settlement_wallet_balance",
            "currency":asset,"balance":str(balance),"target_margin":str(budget),
            "reference":str(price),"contract_value":str(value),"contracts":size,
            "estimated_margin":str(margin),"modeled_fee_room":str(fee_room)}
    if size<1:
        return {"symbol":"BTCUSD","action":"no_trade","reason":"below_one_contract","sizing":detail}
    if margin+fee_room>available:
        return {"symbol":"BTCUSD","action":"no_trade","reason":"insufficient_available_margin_for_target","sizing":detail}
    return {"symbol":"BTCUSD","action":"trade","side":signal["side"],"size":size,
            "leverage":20,"capital_allocation":float(margin),"sizing":detail,
            "reason":"LR-V4-B deterministic 20 percent sizing"}
