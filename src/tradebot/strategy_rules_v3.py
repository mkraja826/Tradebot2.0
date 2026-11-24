from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Rule:
    id:str
    name:str
    frames:tuple
    fields:str
    long:object
    short:object

def evaluate(rule,values):
    missing=[k for k in rule.fields.split() if not isinstance(values.get(k),(float,int)) or not isfinite(values[k])]
    if missing: return {"status":"unavailable","missing":missing}
    sides=[side for side,fn in (("LONG",rule.long),("SHORT",rule.short)) if fn(values)]
    return {"status":"triggered" if sides else "no_signal","directions":sides}

