"""Point-in-time macro annotation of mark research; no gating or execution."""
from .gold_v2_fundamentals import context,collect_external
from .gold_v2_public_feeds import PublicFeeds,feature_packet
from .gold_v2_score import score
from .gold_v2_hybrid import MARK_SOURCE
import time

VERSION="gold-v2-mark-context.1"

class ContextCollector:
    def __init__(self,*,external=collect_external,feeds=None,clock=time.time):
        self.external=external;self.feeds=PublicFeeds() if feeds is None else feeds
        self.clock=clock
    def refresh(self):
        refs,spot=self.external()
        items=self.feeds.collect()
        return {"observed_at":self.clock(),"refs":refs,"spot":spot,"items":items}
    def collect(self,report):
        return self.project(report,self.refresh())
    def project(self,report,snapshot):
        if report.get("signal_source")!=MARK_SOURCE:raise ValueError("wrong_mark_source")
        now=self.clock()
        if not isinstance(snapshot,dict) or not 0<=now-snapshot["observed_at"]<=300:return None
        refs,spot,items=(snapshot[k] for k in ("refs","spot","items"))
        fundamental=context(refs,spot,as_of=now)
        public=feature_packet(items,now)
        scored=score(dict(report,decision_as_of=now,fundamentals=fundamental,public_feeds=public))
        return {"version":VERSION,"as_of":now,"fundamentals":fundamental,"public_feeds":public,
                "intelligence":scored,"snapshot_observed_at":snapshot["observed_at"],"execution_effect":"none"}

def annotate(packet,evidence,*,now):
    """Freeze evidence available before enrollment; never modify price hypotheses."""
    if packet.get("signal_source")!=MARK_SOURCE:raise ValueError("wrong_mark_source")
    if not isinstance(evidence,dict) or evidence.get("version")!=VERSION:
        return dict(packet,macro_annotation={"status":"unavailable","candidate_groups":[]})
    stamp=evidence.get("as_of")
    if type(stamp) not in (int,float) or not 0<=now-stamp<=120:
        return dict(packet,macro_annotation={"status":"unavailable","candidate_groups":[]})
    intel=evidence.get("intelligence",{})
    if intel.get("as_of")!=stamp:
        return dict(packet,macro_annotation={"status":"unavailable","candidate_groups":[]})
    index={(x["family"],x["direction"]):x for x in intel.get("candidates",[])}
    groups=[]
    for h in packet.get("hypotheses",[]):
        row=index.get((h["family"],h["direction"]),{})
        alignment=row.get("macro_alignment")
        group={1:"aligned",-1:"opposed",0:"neutral"}.get(alignment,"unknown")
        groups.append({"family":h["family"],"direction":h["direction"],"macro_group":group,
                       "support_index":row.get("support_index"),"observed_groups":row.get("observed_groups")})
    return dict(packet,macro_annotation={"status":"observed","candidate_groups":groups,
                 "evidence":evidence,"semantics":"prospective_stratification_not_causal_or_learned_filter"})
