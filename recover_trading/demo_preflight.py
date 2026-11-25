"""Read-only deployment check; never print credentials or submit an order."""
import json
import os
from .broker import DeltaDemo
from .decision import configured_models, Provider
from .execution import account_context
from .service import credentials

def main():
    models = configured_models()
    if not Provider().key or not all(models.values()):
        print("AI configuration missing")
        return 1
    try:
        accounts = {symbol: credentials(symbol, os.environ) for symbol in models}
        if len({v[0] for v in accounts.values()}) != len(accounts):
            raise ValueError("Distinct demo keys required")
    except Exception as exc:
        print(json.dumps({"configuration": "unavailable", "error": type(exc).__name__}))
        return 1
    failed = False
    for symbol in models:
        try:
            account = account_context(DeltaDemo(*accounts[symbol]), symbol)
            print(json.dumps({"symbol": symbol, "demo_read": "ok",
                              "wallet_assets": len(account["wallets"]),
                              "model_configured": True}))
        except Exception as exc:
            print(json.dumps({"symbol": symbol, "demo_read": "failed",
                              "error": type(exc).__name__}))
            failed = True
    return int(failed)

if __name__ == "__main__":
    raise SystemExit(main())
