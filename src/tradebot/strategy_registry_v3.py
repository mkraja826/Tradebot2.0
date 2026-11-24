"""Preserve original journal compatibility; validate expanded IDs and timeframes."""
def valid_signal_rule(symbol,rule_id,frame):
    if symbol not in ("BTCUSD","XAUTUSD"): return False
    prefix="B" if symbol=="BTCUSD" else "G"
    if rule_id in {f"{prefix}{i:02}" for i in range(1,26)}:
        return True
    if symbol=="BTCUSD":
        from tradebot.bitcoin_strategies_v3 import RULES
    else:
        from tradebot.gold_strategies_v3 import RULES
    return any(r.id==rule_id and frame in r.frames for r in RULES)
