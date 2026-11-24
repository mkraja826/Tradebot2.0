"""Static mutation-surface inventory; not proof of a single execution boundary."""
import ast
from pathlib import Path

MUTATORS=frozenset(("place_order","cancel_order","cancel_product_orders",
    "cancel_all_orders","edit_order","set_leverage","change_leverage",
    "close_position","close_exposure","place_bracket_order"))

def inventory(root):
    out=[]
    for p in sorted(Path(root).glob("*.py")):
        for n in ast.walk(ast.parse(p.read_text())):
            if not isinstance(n,ast.Call) or not isinstance(n.func,ast.Attribute):continue
            name=n.func.attr
            if name=="_request":
                method=n.args[0] if n.args else next((k.value for k in n.keywords if k.arg=="method"),None)
                if isinstance(method,ast.Constant) and method.value=="GET":continue
                name="request_"+str(method.value) if isinstance(method,ast.Constant) else "request_dynamic"
            elif name not in MUTATORS:continue
            out.append(dict(module=p.name,line=n.lineno,call=name))
    return sorted(out,key=lambda r:(r["module"],r["line"],r["call"]))
