"""Synthetic one-request position-manager smoke probe. Never contacts Delta."""
import argparse
import json
import os
import time
from .decision import Provider, ProviderResponseError
from .exit_context import geometry
from .management_shadow import validate, VERSION
from .management_lifecycle import plan
from .service import DEFAULT_MANAGEMENT_MODEL

SCENARIOS = ("profit_retention", "loss_reduction", "winner_extension")

def context(symbol, scenario, direction):
    if symbol not in ("BTCUSD", "XAUTUSD") or scenario not in SCENARIOS or direction not in ("LONG","SHORT"):
        raise ValueError("invalid fixture")
    sign = 1 if direction == "LONG" else -1
    entry = 60000 if symbol == "BTCUSD" else 3500
    move = {"profit_retention": 1, "loss_reduction": -1, "winner_extension": 2}[scenario]
    mark = entry + sign * entry * move / 100
    stop = entry - sign * entry * 2 / 100
    target = entry + sign * entry * 4 / 100
    other = "SHORT" if sign > 0 else "LONG"
    consensus = direction if scenario == "winner_extension" else other
    p = {"direction":direction.lower(),"size":sign*10,"entry_price":str(entry),
         "mark_price":str(mark),"bracket_state":"matching_legs_observed",
         "legs":[{"type":"stop_loss_order","trigger":str(stop)},
                 {"type":"take_profit_order","trigger":str(target)}]}
    at=int(time.time())
    excursion={"mfe_bps":10 if scenario=="loss_reduction" else 220,"mae_bps":100,
               "coverage":1,"status":"synthetic_fixture"}
    return {"version":VERSION,"symbol":symbol,"as_of":at,"position_observed":at,
            "position":p,"product":{"id":1,"tick_size":"0.1","symbol":symbol},
            "direction_engine":{"direction":consensus},"signals":[],"market":{},
            "coverage":{},"exit_geometry":geometry(p,excursion,direction=consensus),
            "fixture_only":True}

def probe(provider, model, fixture):
    """Exactly one provider request. No execution, no order, no retries."""
    started=time.monotonic()
    out={"model":model,"symbol":fixture["symbol"],"execution_effect":"none",
         "fixture_only":True,"status":"failed"}
    try:
        raw=provider.propose_management(model,fixture)
        proposal=validate(raw,fixture)
        simulated=plan(fixture,proposal)
        out.update(status="valid_proposal",action=proposal["action"],
                   expected_size=simulated["expected_size"],
                   desired_triggers=simulated.get("desired_triggers"))
    except (ValueError,TimeoutError,OSError) as exc:
        out["error"]=type(exc).__name__
        if isinstance(exc,ProviderResponseError):
            out["response_error"]=exc.code
    finally:
        out["elapsed_ms"]=round((time.monotonic()-started)*1000)
        # Copy only known scalar diagnostics, not headers, content or secrets.
        diag=getattr(provider,"diagnostics",{})
        if isinstance(diag,dict):
            out["provider_diagnostics"]={k:diag[k] for k in
                ("elapsed_ms","headers_ms","finish_reason","phase","http_status","transport_failure","usage")
                if k in diag}
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol",choices=("BTCUSD","XAUTUSD"),default="BTCUSD")
    p.add_argument("--scenario",choices=SCENARIOS,default="profit_retention")
    p.add_argument("--direction",choices=("LONG","SHORT"),default="SHORT")
    p.add_argument("--model",default=os.environ.get("RECOVER_MANAGEMENT_MODEL") or DEFAULT_MANAGEMENT_MODEL)
    p.add_argument("--call-provider",action="store_true",help="Explicitly authorize one billable synthetic AI request")
    a=p.parse_args()
    fixture=context(a.symbol,a.scenario,a.direction)
    if not a.call_provider:
        print(json.dumps({"status":"preview_only","model":a.model,"fixture":fixture,
                          "provider_calls":0,"execution_effect":"none"},allow_nan=False))
        return 0
    if not os.environ.get("TB_API_KEY"):
        p.error("TB_API_KEY must already be configured in the process environment")
    result=probe(Provider(),a.model,fixture)
    print(json.dumps(result,allow_nan=False))
    return 0 if result["status"]=="valid_proposal" else 1

if __name__=="__main__":
    raise SystemExit(main())
