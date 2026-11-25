"use strict";
const $=id=>document.getElementById(id);
let chosen="BTCUSD", data=null, busy=false, scope="recover";
const fmt=v=>v===null||v===undefined||v===""?"—":String(v);
const time=v=>typeof v==="number"?new Date(v*1000).toLocaleString():fmt(v);
const human=v=>fmt(v).replaceAll("_"," ");
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=fmt(text);if(cls)n.className=cls;return n}
function empty(id,message="No records available"){ $(id).replaceChildren(el("p",message,"empty")); }
function table(id,rows,cols){
 if(!rows?.length){empty(id,rows===null?"Data unavailable":"No records observed");return}
 const wrap=el("div",undefined,"scroll"),t=el("table"),head=el("thead"),hr=el("tr");
 for(const [label] of cols)hr.append(el("th",label));head.append(hr);t.append(head);
 const body=el("tbody");for(const row of rows){const tr=el("tr");for(const [,get] of cols)tr.append(el("td",get(row)));body.append(tr)}t.append(body);wrap.append(t);$(id).replaceChildren(wrap);
}
function metrics(values,id="metrics"){$(id).replaceChildren(...values.map(([label,value,detail])=>{const box=el("div",undefined,"metric");box.append(el("small",label),el("strong",value),el("small",detail));return box}))}
function chart(id,points){
 const valid=points.filter(p=>p[1]!==null&&p[1]!==undefined&&p[1]!==""&&Number.isFinite(Number(p[1]))).map(p=>[p[0],Number(p[1])]);
 if(valid.length<2){empty(id,"Awaiting at least two observations");return}
 const values=valid.map(p=>p[1]),lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||1;
 const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("viewBox","0 0 540 180");svg.setAttribute("role","img");svg.setAttribute("aria-label","Observed time series");
 const path=document.createElementNS(svg.namespaceURI,"polyline");
 path.setAttribute("points",values.map((v,i)=>[15+i*510/(values.length-1),155-(v-lo)*130/span].join(",")).join(" "));
 path.setAttribute("stroke","#67dfc4");path.setAttribute("stroke-width","2.5");path.setAttribute("fill","none");svg.append(path);
 const caption=el("p",fmt(lo)+" – "+fmt(hi)+" · "+time(valid[0][0])+" → "+time(valid.at(-1)[0]),"empty");
 $(id).replaceChildren(svg,caption);
}
function bars(id,rows){if(!rows?.length){empty(id);return}const total=rows.reduce((s,r)=>s+r.count,0);$(id).replaceChildren(...rows.map(r=>{const x=el("div",undefined,"bar"),p=el("progress");p.max=total||1;p.value=r.count;p.setAttribute("aria-label",human(r.status));x.append(el("span",human(r.status)),p,el("span",r.count));return x}))}
const finite=v=>v!==null&&v!==undefined&&v!==""&&Number.isFinite(Number(v));
const money=(v,currency)=>finite(v)?Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:4})+" "+currency:"—";
const percent=v=>finite(v)?(Number(v)*100).toFixed(1)+"%":"—";
function performanceView(m){
 const p=m.performance||{}, currency=p.currency||"USD", current=scope==="recover", s=(current?p.recover_attributed:p.all_reconciled)||{};
 $("scopeRecover").setAttribute("aria-pressed",String(current));$("scopeAccount").setAttribute("aria-pressed",String(!current));
 $("performanceNote").textContent=(current?"Only closed episodes attributed to a single Recover entry order.":"All reconciled account episodes, including historical/unattributed trades. Not Recover performance.")+" Net P&L and win rate exclude funding. Ledger: "+human(p.status)+".";
 metrics([["Closed episodes",fmt(s.closed_episodes),"Verified subset"],["Win rate",percent(s.win_rate_before_funding),"After commissions, before funding"],["Gross P&L",money(s.gross_pnl,currency),"Before commissions"],["Commissions",money(s.fees,currency),"Closed episodes only"],["Net P&L",money(s.net_before_funding,currency),"Before funding"]],"performanceMetrics");
 const n=s.closed_episodes;
 if(!n){empty("winLoss","No reconciled closed positions in this scope");empty("costBreakdown","No closed-position costs available");}
 else{
  const counts=[["Wins",s.wins_before_funding,"gain"],["Losses",s.losses_before_funding,"loss"],["Breakeven",s.breakeven_before_funding,"neutral"]];
  const track=el("div",undefined,"distribution"),legend=el("div",undefined,"legend");
  for(const [label,count,cls] of counts){
   if(count>0){const part=el("progress",undefined,cls);part.max=n;part.value=count;part.setAttribute("aria-label",label+" "+count+" of "+n);track.append(part);}
   legend.append(el("span",label+": "+fmt(count),cls));
  }
  $("winLoss").replaceChildren(track,legend);
  const list=el("div",undefined,"cost-list");
  for(const [label,v,cls] of [["Gross P&L",s.gross_pnl,"neutral"],["Commissions",s.fees,"loss"],["Net before funding",s.net_before_funding,Number(s.net_before_funding)>=0?"gain":"loss"]]){
   const row=el("div",undefined,"cost-row");row.append(el("span",label),el("strong",money(v,currency),cls));list.append(row);
  }
  $("costBreakdown").replaceChildren(list);
 }
 const episodes=(p.recent_episodes||[]).filter(x=>!current||x.decision_id);
 if(episodes.length){
  let cumulative=0;
  const points=[[episodes[0].opened,0]];
  for(const x of episodes){cumulative+=Number(x.net_before_funding);points.push([x.closed,cumulative]);}
  chart("pnlChart",points);
  $("pnlChart").append(el("p","Cumulative net before funding, starting at zero for displayed recent episodes only. Not an equity curve.","empty"));
 }else empty("pnlChart","No recent reconciled episodes in this scope");
 table("closedEpisodes",episodes.slice().reverse(),[["Closed",r=>r.closed],["Direction",r=>r.direction],["Fills",r=>r.fills],["Gross",r=>money(r.gross_pnl,currency)],["Fees",r=>money(r.fees,currency)],["Net before funding",r=>money(r.net_before_funding,currency)],["Reported funding",r=>money(r.reported_funding,currency)],["Attribution",r=>human(r.attribution)]]);
 table("rulePerformance",Object.entries(p.active_rule_cooccurrence||{}).map(([rule,x])=>({rule,...x})),[["Rule",r=>r.rule],["Episodes",r=>r.closed_episodes],["Win rate",r=>percent(r.win_rate_before_funding)],["Net before funding",r=>money(r.net_before_funding,currency)]]);
 $("rulePerformance").append(el("p","Rules can overlap within a position; totals cannot be summed across rules. Associations do not establish causality.","empty"));
}
function forwardView(m){
 const f=m.forward_validation;
 $("forwardStatus").textContent=f?"Collecting":"Unavailable";
 $("forwardNote").textContent=f?"Started "+time(f.start)+" · Last collection "+time(f.generated)+" · Reference feed: "+human(f.reference_feed)+" · Assumed cost: "+fmt(f.assumed_cost_bps)+" bps round trip.":"No prospective report available.";
 const rows=f?.outcomes||[];
 const count=status=>f?rows.filter(r=>r.status===status).reduce((n,r)=>n+r.count,0):null;
 metrics([["Observed horizons",fmt(count("observed")),"Not unique trades"],["Pending horizons",fmt(count("pending")),"Awaiting future prices"],["Neutral / overlap",f?count("neutral")+count("overlap"):"—","Recorded nonentries"],["Missing reference",fmt(count("missing_reference")),"Not counted as losses"],["New demo fills",fmt(f?.actual_demo?.fills),"Observed since protocol start"]],"forwardMetrics");
 table("forwardRows",f?rows:null,[["Horizon",r=>r.horizon_s/60+" min"],["Status",r=>human(r.status)],["Outcomes",r=>r.count],["Avg net return",r=>finite(r.mean_net_bps)?Number(r.mean_net_bps).toFixed(3)+" bps":"—"],["Positive outcomes",r=>r.status==="observed"?r.wins:"—"]]);
}
function render(){
 if(!data)return;
 const m=data.markets.find(x=>x.symbol===chosen);if(!m)return;
 const snap=m.snapshot||{},h=m.heartbeat||{},wallets=snap.wallets,positions=snap.positions;
 const alerts=[];if(!h.timestamp)alerts.push("Worker heartbeat unavailable");else if(Date.now()/1000-h.timestamp>180)alerts.push("Worker observation older than 3 minutes");
 if(!m.availability.wallets)alerts.push("Wallet data unavailable");if(Object.keys(snap.errors||{}).length)alerts.push("Exchange observations incomplete");
 if(snap.observed&&Date.now()/1000-snap.observed>180)alerts.push("Position snapshot may be stale");
 if(h.status==="cycle_error")alerts.push("Latest cycle reported an error");
 const pf=m.postfill_bracket||{};
 if(pf.status==="bracket_evidence_missing_or_mismatched")alerts.push("Open position: matching SL/TP legs not verified");
 if(pf.entry_evidence?.bracket_price_geometry===false)alerts.push("Recorded SL/TP prices do not straddle the matched entry fill correctly");
 $("warning").textContent=alerts.join(" • ");
 const sum=rows=>rows?.reduce((s,r)=>s+r.count,0)??null;
 metrics([["Market price",fmt(m.prices.at(-1)?.close),"Last recorded 5m close"],["Open positions",positions?.length??"—","Exchange observation"],["AI decisions",fmt(sum(m.decision_counts)),"Journal count"],["Order submissions",fmt(sum(m.order_counts)),"Not completed trades"],["Recover win rate",percent(m.performance?.recover_attributed?.win_rate_before_funding),"Reconciled, before funding"],["Recover net P&L",money(m.performance?.recover_attributed?.net_before_funding,m.performance?.currency||"USD"),"Closed episodes, before funding"]]);
 performanceView(m);forwardView(m);
 const quality=h.market_quality||{}, recent=quality.recent_24h, timing=h.cycle_timing_ms||{};
 $("qualityNote").textContent="Demo source only · "+(recent?recent.rows+" / "+recent.expected_rows+" five-minute candles · "+recent.opening_gaps_gt_1pct+" opening gaps >1% · "+recent.ranges_gt_2pct+" ranges >2%":"Candle quality unavailable")+" · Cycle duration: "+fmt(timing.total)+" ms. Diagnostic only; no execution effect.";
 table("qualityFrames",Object.entries(quality.frames||{}).map(([frame,r])=>({frame,...r})),[["Timeframe",r=>r.frame],["Collection",r=>human(r.collection_status)],["Snapshot",r=>human(r.snapshot_status)],["Last close",r=>time(r.closed_at)],["Lag at scan (s)",r=>r.lag_at_scan_s],["Lag at observation (s)",r=>r.lag_at_observation_s],["Reason",r=>human(r.collection_reason)]]);
 table("qualityQuotes",Object.entries(quality.quotes||{}).map(([feed,r])=>({feed,...r})),[["Feed",r=>r.feed],["Collection",r=>human(r.collection_status)],["Age (s)",r=>r.age_s]]);
 chart("price",m.prices.map(p=>[p.time,p.close]));
 const asset=wallets?.[0]?.asset_symbol;
 chart("walletChart",asset?m.wallet_history.map(p=>[p.observed,p.wallets.find(w=>w.asset_symbol===asset)?.balance]):[]);
 if(asset)$("walletChart").append(el("p","Chart asset: "+asset,"empty"));
 const dual=m.dual_market, df=Object.entries(dual?.frames||{}).map(([frame,r])=>({frame,...r}));
 $("dualNote").textContent=dual?"Collected "+time(dual.generated)+" · Reference and demo sources remain separate.":"Reference comparison unavailable.";
 table("dualFrames",dual?df:null,[["Frame",r=>r.frame],["Status",r=>human(r.status)],["Close time",r=>time(r.closed_at)],["Lag s",r=>r.lag_s],["Demo close",r=>r.demo_close],["Reference close",r=>r.reference_close],["Difference bps",r=>finite(r.signed_close_difference_bps)?Number(r.signed_close_difference_bps).toFixed(2):"—"],["Agreement",r=>finite(r.comparable_count)?r.agreement_count+"/"+r.comparable_count:"—"]]);
 table("dualIndicators",dual?df.flatMap(r=>Object.entries(r.indicators||{}).map(([indicator,v])=>({frame:r.frame,indicator,...v}))):null,[["Frame",r=>r.frame],["Indicator",r=>human(r.indicator)],["Demo",r=>finite(r.demo)?Number(r.demo).toFixed(4):"—"],["Reference",r=>finite(r.reference)?Number(r.reference).toFixed(4):"—"]]);
 const sr=m.reference_strategy;
 $("referenceStrategyNote").textContent=sr?"Cutoff "+time(sr.as_of)+" · Matched demo: "+fmt(sr.matched_demo?.direction)+" · Matched reference: "+fmt(sr.matched_reference?.direction)+" · Comparable rule/timeframes: "+fmt(sr.comparable_rule_frames):"Reference strategy comparison unavailable.";
 bars("referenceStrategyCounts",Object.entries(sr?.comparison_counts||{}).map(([status,count])=>({status,count})));
 table("referenceStrategyRows",sr?.rows??null,[["Rule",r=>r.id+" "+r.name],["Frame",r=>r.frame],["Demo",r=>r.demo===null?"Unavailable":r.demo.join(", ")||"Inactive"],["Reference",r=>r.reference===null?"Unavailable":r.reference.join(", ")||"Inactive"],["Comparison",r=>human(r.comparison)]]);
 const paired=m.paired_forward;
 $("pairedNote").textContent=paired?"Protocol started "+time(paired.start)+" · Last collection "+time(paired.generated)+" · Assumed cost "+fmt(paired.assumed_cost_bps)+" bps · "+human(paired.reference_feed):"Paired forward research unavailable.";
 const pairedBps=v=>finite(v)?Number(v).toFixed(3)+" bps":"—";
 const pairedRows=paired?paired.horizons.flatMap(r=>[{...r,scope:"All paired windows"},{...r.disagreement_only,horizon_s:r.horizon_s,scope:"Disagreement only"}]):null;
 table("pairedRows",pairedRows,[["Horizon",r=>r.horizon_s/60+"m"],["Scope",r=>r.scope],["Completed",r=>r.paired_windows],["Pending",r=>r.counts?.pending??"—"],["Demo entries",r=>r.demo_entries],["Reference entries",r=>r.reference_entries],["Demo / window",r=>pairedBps(r.mean_demo_net_bps_per_window)],["Reference / window",r=>pairedBps(r.mean_reference_net_bps_per_window)],["Paired difference",r=>pairedBps(r.mean_reference_minus_demo_bps)]]);
 const pc=m.planner_comparison;
 $("plannerComparisonNote").textContent=pc?"Started "+time(pc.start)+" · Prepared pairs "+fmt(pc.prepared_pairs)+" · Experimental proposals "+fmt(pc.experimental_proposals)+" · Latest evidence "+human(pc.latest?.evidence_status):"Planner comparison unavailable.";
 bars("plannerComparisonCounts",Object.entries(pc?.evidence_counts||{}).map(([status,count])=>({status,count})));
 table("wallet",wallets??null,[["Asset",r=>r.asset_symbol],["Balance",r=>r.balance],["Available",r=>r.available_balance],["Position margin",r=>r.position_margin],["Order margin",r=>r.order_margin]]);
 $("brackets").textContent="Bracket evidence: "+human(snap.bracket_evidence)+" · Observed "+time(snap.observed)+" · Not a coverage guarantee.";
 const pp=m.position_preview||{};
 $("positionPreviewNote").textContent="Position: "+human(pp.position_state)+" · Contracts: "+fmt(pp.size)+" · Bracket: "+human(pp.bracket_state)+" · Unresolved submissions: "+fmt(pp.unresolved_submissions);
 table("positionPreviewLegs",pp.legs??null,[["Leg",r=>human(r.type)],["Trigger",r=>r.trigger],["Remaining",r=>r.remaining],["Quantity matches",r=>r.matching_quantity?"Yes":"No"],["Side matches",r=>r.matching_side?"Yes":"No"],["Reduce only",r=>r.reduce_only?"Yes":"No"]]);
 const ox=m.open_excursion||{};
 $("openExcursion").textContent="Open position: "+human(ox.status)+(ox.mfe_bps==null?"":" · MFE "+fmt(ox.mfe_bps)+" bps · MAE "+fmt(ox.mae_bps)+" bps · Mark return "+fmt(ox.current_mark_return_bps)+" bps · Interior coverage "+(ox.coverage==null?"—":fmt(ox.coverage*100)+"%"));
 const ex=m.trade_excursions||{};
 $("excursionNote").textContent="Observed lower bounds from completed interior candles; boundary candles excluded. "+human(ex.status);
 table("excursionRows",(ex.episodes||[]).slice().reverse(),[["Closed",r=>r.closed],["Direction",r=>r.direction],["MFE bps",r=>fmt(r.mfe_bps)],["MAE bps",r=>fmt(r.mae_bps)],["Coverage",r=>r.coverage==null?"—":fmt(r.coverage*100)+"%"],["Evidence",r=>human(r.status)]]);
 const mr=m.management_report||{};
 $("managementRuntime").textContent="Management: "+(mr.enabled===true?"Enabled":mr.enabled===false?"Disabled":"Unverified")+" · "+human(mr.runtime_status)+" · Latest: "+human(mr.latest?.status)+" "+human(mr.latest?.action);
 bars("managementEvaluations",Object.entries(mr.evaluations||{}).map(([status,count])=>({status,count})));
 bars("managementActions",Object.entries(mr.actions||{}).map(([status,count])=>({status,count})));
 $("managementLatency").textContent="Median provider response: "+(mr.median_response_ms==null?"Unavailable":fmt(mr.median_response_ms/1000)+" s")+" · "+fmt(mr.latency_samples)+" timed responses";
 table("managementAttemptTable",mr.autonomous_attempts||[],[["Action",r=>human(r.action)],["Status",r=>human(r.status)],["Count",r=>fmt(r.count)]]);
 table("manualManagementEvidence",mr.manual_exchange_evidence||[],[["Test",r=>human(r.kind)],["Status",r=>human(r.status)],["Order ID",r=>r.order_id],["Trigger / remaining",r=>r.trigger??r.remaining_contracts]]);
 const mc=m.management_compat||{};
 $("managementNote").textContent="Status: "+human(mc.status)+" · Amendment: "+human(mc.amendment)+" · Close: "+human(mc.reduce_only_close)+" · Historical fills: "+fmt(mc.historical_fills);
 bars("managementCounts",Object.entries(mc.fill_transitions||{}).map(([status,count])=>({status,count})));
 table("positions",positions??null,[["Contracts",r=>r.size],["Entry",r=>r.entry_price],["Mark",r=>r.mark_price],["Margin",r=>r.margin],["Unrealized P&L",r=>r.unrealized_pnl],["Liquidation",r=>r.liquidation_price]]);
 table("active",snap.active_orders??null,[["Type",r=>human(r.stop_order_type)],["Side",r=>r.side],["Size",r=>r.size],["Trigger",r=>r.stop_price],["State",r=>human(r.state)]]);
 const coverage=h.coverage||{}; $("strategies").replaceChildren(el("p","Latest cycle: "+human(h.status)),el("p","Signals: "+fmt(h.signal_count)+" · Evaluable: "+fmt(coverage.evaluable_rules)+" / "+fmt(coverage.implemented_rules)+" · Deferred: "+fmt(coverage.deferred_rules)));
 const dir=h.direction_engine||{}, rg=dir.regime||{}, research=m.signal_research||[];
 $("strategies").append(el("p","Direction: "+fmt(dir.direction)+" · "+human(rg.regime)+" · Volatility: "+human(rg.volatility)),
 el("p","Weighted LONG: "+fmt(dir.long_score)+" · SHORT: "+fmt(dir.short_score)+" (scores, not probabilities)"),
 el("p","Research horizon samples: "+research.reduce((n,x)=>n+x.samples,0)+" · Observed: "+research.reduce((n,x)=>n+x.observed,0)+" · Pending: "+research.reduce((n,x)=>n+x.pending,0)+" · Missed: "+research.reduce((n,x)=>n+x.missed,0)));
 const rows=research.filter(x=>x.observed>0).slice(0,20);
 if(rows.length){const list=el("ul");for(const x of rows)list.append(el("li",x.rule_id+" · "+human(x.regime)+" · "+x.horizon_s/60+"m · "+x.observed+" observations · "+fmt(x.avg_mark_return_bps)+" bps average"));$("strategies").append(list)}
 $("strategies").append(el("p","Research uses forward mark-price returns, not executed trade P&L. Full per-rule aggregates are in the dashboard API.","empty"));
 const opp=h.opportunity||{},atr=opp.atr_by_frame?.["15m"];
 $("strategies").append(el("p","Opportunity evidence: "+human(opp.status)+" · Mark: "+fmt(opp.reference_price)+" · Spread (bps): "+fmt(opp.observed_spread_bps)),
 el("p","15m ATR (bps): "+fmt(atr?.atr_bps)+" · Nearest below: "+fmt(opp.nearest_below?.price)+" · Above: "+fmt(opp.nearest_above?.price)),
 el("p","Illustrative round-trip cost: "+fmt(opp.assumed_round_trip_cost_bps)+" bps. Research evidence only; not a trade instruction.","empty"));
 bars("counts",m.order_counts);
 const review=m.decision_review||{};
 $("reviewNote").textContent="Status: "+human(review.status)+" · Decisions: "+fmt(review.decision_count)+" · Entry deviation samples: "+fmt(review.entry_deviation_samples);
 bars("reviewCounts",Object.entries(review.outcome_counts||{}).map(([status,count])=>({status,count})));
 bars("reviewFailures",Object.entries(review.failure_counts||{}).map(([status,count])=>({status,count})));
 const bps=v=>finite(v)?Number(v).toFixed(2):"—";
 table("reviewRows",review.recent?.slice().reverse()??null,[["Time",r=>time(r.created)],["Outcome",r=>human(r.outcome)],["Direction",r=>r.direction],["Filled",r=>r.filled_contracts],["Entry deviation bps",r=>bps(r.entry_deviation_bps)],["Plan SL bps",r=>bps(r.planned_stop_bps)],["Plan TP bps",r=>bps(r.planned_target_bps)],["Reward/risk",r=>bps(r.planned_reward_risk)],["Net before funding",r=>money(r.net_before_funding,m.performance?.currency||"USD")]]);
 table("decisions",m.availability.decisions?m.decisions:null,[["Time",r=>time(r.created)],["Model",r=>r.model],["Decision",r=>human(r.result?.action||r.status)],["Side",r=>r.result?.side],["Capital budget",r=>r.result?.capital_allocation],["Size",r=>r.result?.size],["SL",r=>r.result?.stop_loss],["TP",r=>r.result?.take_profit],["Signals",r=>r.signals.map(s=>s.id+" "+s.frame).join(", ")],["Reason",r=>r.result?.reason||r.result?.error]]);
 const sa=m.submission_audit||{};
 $("submissionNote").textContent="Status: "+human(sa.status)+" · Misaligned brackets: "+fmt(sa.misaligned_brackets)+" · Unknown alignment: "+fmt(sa.unknown_tick_alignment);
 table("submissionRows",sa.recent?.slice().reverse()??null,[["Submission",r=>human(r.status)],["Position at decision",r=>human(r.position_at_decision)],["Side",r=>r.side],["Tick alignment",r=>r.tick_alignment===null?"Unknown":r.tick_alignment?"Aligned":"Misaligned"],["HTTP status",r=>r.http_status],["Exchange code",r=>r.exchange_code]]);
 table("orders",m.orders,[["Client ID",r=>r.client_id.slice(0,12)],["Submission",r=>human(r.status)],["Exchange state",r=>human(r.exchange?.status)],["Side",r=>r.intent?.side],["Size",r=>r.intent?.size],["Filled",r=>r.exchange?.filled_size],["Fill price",r=>r.exchange?.order?.average_fill_price],["SL",r=>r.intent?.stop_loss],["TP",r=>r.intent?.take_profit]]);
 table("fills",m.fills?.filter(Boolean)??null,[["Time",r=>r.created_at],["Fill ID",r=>r.id],["Side",r=>r.side],["Size",r=>r.size],["Price",r=>r.price],["Fee",r=>r.commission],["Asset",r=>r.settling_asset_symbol],["Position realized P&L*",r=>r.new_position?.realized_pnl]]);
 $("fills").append(el("p","* Exchange position metadata may be cumulative; not summed as per-trade profit.","empty"));
}
$("scopeRecover").addEventListener("click",()=>{scope="recover";render()});
$("scopeAccount").addEventListener("click",()=>{scope="account";render()});
for(const b of document.querySelectorAll("nav button"))b.addEventListener("click",()=>{chosen=b.dataset.symbol;for(const x of document.querySelectorAll("nav button"))x.setAttribute("aria-pressed",String(x===b));render()});
async function refresh(){if(busy)return;busy=true;try{const r=await fetch("/api/overview",{cache:"no-store"});if(!r.ok)throw Error();data=await r.json();render();$("refresh").textContent="Updated "+time(data.generated)}catch{$("refresh").textContent="Refresh failed · retained data";$("warning").textContent="Dashboard connection unavailable. Previously displayed data may be stale."}finally{busy=false}}
refresh();setInterval(refresh,10000);