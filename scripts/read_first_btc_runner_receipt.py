"""Read the first BTC runner receipt and current demo protection from the VM."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from decimal import Decimal

proc = Path("/proc") / subprocess.check_output(
    ["systemctl", "show", "recover-demo.service", "-p", "MainPID", "--value"], text=True).strip()
root = (proc / "cwd").resolve()
args = (proc / "cmdline").read_bytes().decode().split("\0")
data = Path("data/recover-service")
for i, arg in enumerate(args):
    if arg == "--data-dir":
        data = Path(args[i + 1])
    elif arg.startswith("--data-dir="):
        data = Path(arg.split("=", 1)[1])
env = dict(x.split("=", 1) for x in (proc / "environ").read_bytes().decode().split("\0") if "=" in x)
sys.path.insert(0, str(root))
from recover_trading.service import credentials
from recover_trading.broker import DeltaDemo

broker = DeltaDemo(*credentials("BTCUSD", env))
wallet, = [w for w in broker.wallet()["result"] if w["asset_symbol"] == "USD"]
if str(wallet.get("user_id")) != "26679287":
    raise SystemExit("BTC wallet mismatch")
db = sqlite3.connect((root / data / "BTCUSD/orders.sqlite").resolve().as_uri()+"?mode=ro", uri=True)
row = db.execute("SELECT client_id,stop FROM btc_runner_entries ORDER BY created,rowid LIMIT 1").fetchone()
if not row:
    raise SystemExit("No BTC runner entry record")
receipt = broker.order(row[0])
pid = broker.product("BTCUSD")["id"]
if receipt.get("client_order_id") != row[0] or receipt.get("product_id") != pid:
    raise SystemExit("Entry receipt identity mismatch")
positions = broker.positions(pid)
if isinstance(positions, dict):
    positions = [positions]
page = broker.active_orders_page(pid)
def fields(record, keys):
    return {k:record.get(k) for k in keys.split()}
print(json.dumps({"first_entry": fields(receipt,"id state side size unfilled_size average_fill_price"),
                  "filled_contracts":str(Decimal(str(receipt["size"]))-Decimal(str(receipt["unfilled_size"]))),
                  "initial_stop":row[1],"current_positions":[fields(p,"size entry_price") for p in positions],
                  "current_orders":[fields(o,"id state side size stop_order_type stop_price stop_trigger_method") for o in page["result"]],
                  "additional_order_pages":bool(page.get("meta",{}).get("after"))},indent=2))
