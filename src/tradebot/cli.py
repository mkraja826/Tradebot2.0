"""Read-only CLI for the first milestone; demo orders require explicit integration."""
import argparse
import json
from datetime import datetime, timezone

from tradebot.delta import DeltaDemo
from tradebot.session import session_phase, NEW_YORK


def main() -> None:
    parser = argparse.ArgumentParser(description="Tradebot 2.0 (Delta India demo only)")
    parser.add_argument("command", choices=("status", "catalog"))
    args = parser.parse_args()
    if args.command == "status":
        instant = datetime.now(timezone.utc)
        print(json.dumps({
            "environment": "delta-india-demo",
            "orders": "disabled-in-cli",
            "time_ny": instant.astimezone(NEW_YORK).isoformat(),
            "phase": session_phase(instant).value,
        }, indent=2))
    else:
        contracts = DeltaDemo().products()
        print(json.dumps({
            "environment": "delta-india-demo",
            "btc_derivative_count": len(contracts),
            "sample": [{"symbol": c["symbol"], "id": c["id"],
                        "contract_type": c["contract_type"]}
                       for c in contracts[:15]],
        }, indent=2))


if __name__ == "__main__":
    main()
