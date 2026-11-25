"""Describe completed historical replay, without learning or deploying weights."""
import argparse,json
from pathlib import Path
def leaderboard(report,*,minimum=20,horizon=3600):
    if not report.get("complete"):
        raise ValueError("replay incomplete")
    rows=[r for r in report["results"] if r["partition"]=="holdout" and r["regime"]=="all" and r["horizon_s"]==horizon]
    eligible=[r for r in rows if not r["rule_id"].startswith("ensemble_") and r["samples"]>=minimum]
    return {"symbol":report["symbol"],"horizon_s":horizon,"minimum_samples":minimum,
            "eligible_rules":len(eligible),"ranked":sorted(eligible,key=lambda r:(-r["mean_net_bps"],-r["samples"],r["rule_id"])),
            "insufficient_samples":[r for r in rows if not r["rule_id"].startswith("ensemble_") and r["samples"]<minimum],
            "ensembles":[r for r in rows if r["rule_id"].startswith("ensemble_")],
            "note":"Descriptive holdout results; ranking is not independent validation or a deployed weight change."}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("report");p.add_argument("--horizon",type=int,default=3600);p.add_argument("--minimum",type=int,default=20);a=p.parse_args()
    print(json.dumps(leaderboard(json.loads(Path(a.report).read_text()),minimum=a.minimum,horizon=a.horizon),indent=2))
if __name__=="__main__":main()
