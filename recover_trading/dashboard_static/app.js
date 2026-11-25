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

function advancedPerformance(m){
 const p=m.performance_analytics||{},s=p[scope]||{},currency=p.currency||"USD",ready=s.status==="observed"||s.status==="empty";
 $("advancedScopeNote").textContent=ready?fmt(s.episodes)+" of "+fmt(s.expected_reconciled_episodes)+" reconciled closed episodes · "+(s.truncated?"Recent subset; older episodes excluded":"All currently reconciled episodes in scope")+" · Advanced statistics exclude funding.":"Advanced performance unavailable.";
 const pf=finite(s.profit_factor)?Number(s.profit_factor).toFixed(2):s.profit_factor_status==="no_losing_episodes"?"No losses":"—";
 metrics([["Profit factor",pf,"Positive net / absolute negative net"],["Average net",money(s.average_net,currency),"Per closed episode"],["Average win",money(s.average_win,currency),"Positive closed episodes"],["Average loss",money(s.average_loss,currency),"Negative closed episodes"],["Max closed P&L drawdown",money(s.max_closed_pnl_drawdown,currency),"From prior cumulative peak; not equity"],["Sample size",fmt(s.episodes),"Recent reconciled subset"]],"advancedMetrics");
 if(s.curve?.length){
  const first=s.curve[0].closed;
  chart("pnlChart",[[first,0],...s.curve.map(x=>[x.closed,x.cumulative_net])]);
  $("pnlChart").append(el("p","Cumulative net before funding, starting at zero. X-axis follows closure events, not elapsed time. Not account equity.","empty"));
  chart("drawdownChart",[[first,0],...s.curve.map(x=>[x.closed,-Number(x.drawdown)])]);
  $("drawdownChart").append(el("p","Peak-to-trough decline in displayed cumulative closed P&L only, negative USD. Excludes open-position movement.","empty"));
 }else{empty("drawdownChart","No reconciled closures");empty("pnlChart","No reconciled closures")}
 const directions=$("directionResults");directions.replaceChildren();
 for(const r of s.directions||[]){const row=el("div",undefined,"direction-result");row.append(el("strong",r.direction+" · "+r.episodes+" episodes"),el("strong",money(r.net,currency),finite(r.net)?Number(r.net)>=0?"gain":"loss":""),el("small",r.wins+" wins / "+r.losses+" losses"));directions.append(row)}
 if(!directions.children.length)empty("directionResults","Unavailable");
 const cal=$("profitCalendar");cal.replaceChildren();
 const dates=s.calendar||[];if(dates.length){
  const offset=(new Date(dates[0].date+"T00:00:00Z").getUTCDay()+6)%7;
  for(const day of ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])cal.append(el("span",day,"calendar-weekday"));
  for(let i=0;i<offset;i++)cal.append(el("span",undefined,"calendar-spacer"));
  for(const r of dates){const v=finite(r.net)?Number(r.net):null,cell=el("div",undefined,"calendar-cell "+(v===null?"calendar-empty":v>0?"calendar-win":v<0?"calendar-loss":"calendar-flat"));
   cell.append(el("small",r.date.slice(8)),el("strong",v===null?"—":(v>0?"+":"")+v.toFixed(2)),el("small",r.episodes?r.episodes+" closed":"No record"));cell.title=r.date+" UTC · "+money(r.net,currency)+" · "+r.episodes+" recorded episodes";cal.append(cell)}
 }else cal.append(el("p","Calendar unavailable","empty"));
 const ret=s.retention||{};
 $("retentionSummary").replaceChildren(el("p",fmt(ret.eligible_episodes)+" eligible episodes · Median observed capture upper bound: "+(finite(ret.median_capture_upper_bound_pct)?Number(ret.median_capture_upper_bound_pct).toFixed(1)+"%":"Unavailable"),"empty"));
 const list=$("retentionRows");list.replaceChildren();
 for(const r of (ret.rows||[]).slice().reverse()){
  const row=el("div",undefined,"retention-row");row.append(el("small",r.direction+" · "+r.closed));
  const bars=el("div",undefined,"retention-bars");
  for(const [label,v,cls] of [["Observed MFE",r.mfe_bps,"neutral"],["Gross weighted exit",r.gross_exit_bps,"gain"]]){const b=el("div",undefined,"retention-bar"),pr=el("progress",undefined,cls);pr.max=r.mfe_bps;pr.value=v;pr.setAttribute("aria-label",label);b.append(el("span",label),pr,el("strong",v.toFixed(2)+" bps"));bars.append(b)}
  row.append(bars,el("small","Capture upper bound "+r.capture_upper_bound_pct.toFixed(1)+"%","empty"));list.append(row)
 }
 if(!list.children.length)empty("retentionRows","No eligible excursion evidence");
}
function donutView(s){
 const wrap=$("winLoss");if(!s.closed_episodes)return;
 const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg"),n=Number(s.closed_episodes);
 svg.setAttribute("viewBox","0 0 220 140");svg.setAttribute("role","img");svg.setAttribute("aria-label","Closed episode outcomes");
 const counts=[["Wins",s.wins_before_funding,"#29c99a"],["Losses",s.losses_before_funding,"#f27783"],["Breakeven",s.breakeven_before_funding,"#8190a3"]];
 const circle=(c,frac,offset)=>{const r=document.createElementNS(ns,"circle");for(const [k,v] of Object.entries({cx:70,cy:70,r:46,fill:"none",stroke:c,"stroke-width":14,"pathLength":100,"stroke-dasharray":frac+" "+(100-frac),"stroke-dashoffset":-offset,transform:"rotate(-90 70 70)"}))r.setAttribute(k,String(v));svg.append(r)};
 let offset=0;for(const [label,v,c] of counts){if(v>0){const share=100*v/n;circle(c,share,offset);offset+=share}}
 const txt=(x,y,v,size,color,anchor)=>{const t=document.createElementNS(ns,"text");for(const [k,w] of Object.entries({x,y,"font-size":size,fill:color,"text-anchor":anchor}))t.setAttribute(k,String(w));t.textContent=v;svg.append(t)};
 txt(70,68,String(n),23,"#eef2f6","middle");txt(70,84,"closed",10,"#9eabbc","middle");
 counts.forEach(([label,v,c],i)=>txt(132,45+i*25,label+" "+fmt(v),11,c,"start"));
 wrap.replaceChildren(svg);
}

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
 donutView(s);advancedPerformance(m);
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

// Application navigation and two-account overview. No trading mutations.
const workspacePages=Array.from(document.querySelectorAll("[data-workspace]"));
function navigate(page,focus=false){
 const target=workspacePages.find(n=>n.dataset.workspace===page)||workspacePages[0];
 for(const n of workspacePages)n.hidden=n!==target;
 for(const b of document.querySelectorAll("[data-page]")){if(b.dataset.page===target.dataset.workspace)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current")}
 $("pageTitle").textContent=target.dataset.title;$("pageSubtitle").textContent=target.dataset.description;
 $("workspaceNav").classList.remove("expanded");$("morePages").setAttribute("aria-expanded","false");
 if(focus){$("workspace").focus({preventScroll:true});window.scrollTo({top:0,behavior:"instant"})}
}
function route(page){if(location.hash==="#"+page)navigate(page,true);else location.hash=page}
for(const b of document.querySelectorAll("[data-page],[data-route]"))b.addEventListener("click",()=>route(b.dataset.page||b.dataset.route));
$("morePages").addEventListener("click",()=>{const open=$("workspaceNav").classList.toggle("expanded");$("morePages").setAttribute("aria-expanded",String(open))});
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&$("workspaceNav").classList.contains("expanded")){$("workspaceNav").classList.remove("expanded");$("morePages").setAttribute("aria-expanded","false");$("morePages").focus()}});
window.addEventListener("hashchange",()=>{if(location.hash!=="#workspace")navigate(location.hash.slice(1),true)});
navigate(location.hash.slice(1));
function chooseMarket(symbol){if(!["BTCUSD","XAUTUSD"].includes(symbol))return;chosen=symbol;for(const x of document.querySelectorAll("[data-symbol]"))x.setAttribute("aria-pressed",String(x.dataset.symbol===symbol));render();document.dispatchEvent(new CustomEvent("recover:market",{detail:symbol}))}
function ageLabel(h){const age=Date.now()/1000-Number(h?.timestamp);return finite(h?.timestamp)&&age>=-5&&age<=180&&h.status!=="cycle_error"?"Recent heartbeat":finite(h?.timestamp)?"Check worker":"Unverified"}
function overviewView(){
 const ms=data.markets||[], stats=ms.map(m=>m.performance?.recover_attributed||{}), currency=ms.length===2&&ms.every(m=>m.performance?.currency==="USD")?"USD":null;
 const complete=currency&&ms.every(m=>m.performance?.status==="reconciled_subset")&&stats.every(s=>finite(s.closed_episodes)&&Number(s.closed_episodes)>=0&&(Number(s.closed_episodes)===0||finite(s.net_before_funding)));
 const total=complete?stats.reduce((a,s)=>a+(Number(s.closed_episodes)===0?0:Number(s.net_before_funding)),0):null;
 $("overviewNet").textContent=money(total,"USD");$("overviewNet").className=finite(total)?Number(total)>=0?"gain":"loss":"";
 $("overviewClosed").textContent=complete?String(stats.reduce((a,s)=>a+Number(s.closed_episodes),0)):"—";
 $("overviewWorkers").textContent=ms.length?ms.filter(m=>ageLabel(m.heartbeat)==="Recent heartbeat").length+"/"+ms.length:"—";
 $("overviewCoverage").textContent=ms.length===2&&ms.every(m=>finite(m.heartbeat?.coverage?.evaluable_rules))?ms.reduce((a,m)=>a+Number(m.heartbeat.coverage.evaluable_rules),0)+"/100":"—";
 const cards=ms.map(m=>{
  const p=m.position_preview||{},h=m.heartbeat||{},s=m.performance?.recover_attributed||{},pos=m.snapshot?.positions;
  const card=el("article",undefined,"account-card"),top=el("div",undefined,"account-top"),coin=el("span",m.symbol==="BTCUSD"?"₿":"Au","coin "+(m.symbol==="BTCUSD"?"btc":"gold")),label=el("div",undefined,"account-name");
  label.append(el("strong",m.symbol==="BTCUSD"?"Bitcoin":"Gold"),el("small",m.symbol));
  const status=ageLabel(h);top.append(coin,label,el("span",status,"account-status "+(status==="Recent heartbeat"?"gain":"caution")));
  const val=el("div",undefined,"account-value");val.append(el("small","Recover net · before funding"),el("strong",money(s.net_before_funding,m.performance?.currency||"USD"),finite(s.net_before_funding)?Number(s.net_before_funding)>=0?"gain":"loss":""));
  const fields=el("dl",undefined,"account-fields");
  const side=finite(p.size)&&Number(p.size)!==0?(Number(p.size)>0?"LONG":"SHORT")+" · "+Math.abs(Number(p.size))+" contracts":Array.isArray(pos)&&pos.length===0?"Flat":"Unverified";
  const raw=Array.isArray(pos)&&pos.length===1?pos[0]:null;
  for(const [k,v] of [["Position",side],["Mark price",money(p.mark_price,"USD")],["Unrealized P&L*",money(raw?.unrealized_pnl,"USD")],["SL / TP",p.bracket_state==="matching_legs_observed"?"Matching legs observed":human(p.bracket_state)],["Market regime",human(h.direction_engine?.regime?.regime)]]){fields.append(el("dt",k),el("dd",v))}
  const open=el("button","View market →","quiet-button");open.addEventListener("click",()=>{chooseMarket(m.symbol);route("live")});card.append(top,val,fields,open);return card;
 });
 $("overviewAccounts").replaceChildren(...cards);
 if(cards.length)$("overviewAccounts").append(el("p","* Exchange-reported unrealized P&L; not realized return. Heartbeat status does not guarantee execution readiness.","empty overview-footnote"));
}


let aiFilter="all",aiLastKey="",aiExpanded=new Set();
const aiNumber=x=>finite(x)?Number(x).toLocaleString(undefined,{maximumFractionDigits:2}):"—";
const aiLabel=x=>x==null?"Unavailable":human(x);
const aiText=x=>typeof x==="string"?x.slice(0,1500):null;
function aiEvents(m){
 const review=new Map((m.decision_review?.recent||[]).map(r=>[r.id,r]));
 const attempts=new Map((m.management_attempts||[]).map(r=>[r.proposal_id,r]));
 const entry=(m.decisions||[]).map(d=>{
  const r=d.result||{},v=review.get(d.id)||{};
  return {key:"entry:"+d.id,type:"entry",created:d.created,status:d.status,action:r.action,side:r.side,reason:aiText(r.reason),error:aiText(r.response_error||r.error),outcome:v.outcome,execution:v.order_status,net:v.net_before_funding,model:d.model,rules:d.signals||[],size:r.size,sl:r.stop_loss,tp:r.take_profit};
 });
 const management=(m.management_shadow?.recent||[]).map(d=>{
  const r=d.result||{},p=r.proposal||{},a=attempts.get(d.id);
  return {key:"management:"+d.id,type:"management",created:d.created,status:d.status,action:p.action,reason:aiText(p.reason),error:aiText(r.response_error||r.error),execution:a?.status,executionAction:a?.action,executionTime:a?.created};
 });
 return [...entry,...management].filter(e=>Number.isInteger(e.created)).sort((a,b)=>b.created-a.created||a.key.localeCompare(b.key));
}
function aiEvidence(m){
 const h=m.heartbeat||{},d=h.direction_engine||{},reg=d.regime||{},age=Date.now()/1000-Number(h.timestamp);
 const fresh=finite(h.timestamp)&&age>=-5&&age<=180&&h.status!=="cycle_error";
 const valid=["LONG","SHORT","NEUTRAL"].includes(d.direction);
 $("aiDirection").textContent=valid?d.direction==="LONG"?"Bullish consensus":d.direction==="SHORT"?"Bearish consensus":"Neutral consensus":"Consensus unavailable";
 $("aiDirection").className=valid?(d.direction==="LONG"?"gain":d.direction==="SHORT"?"loss":""):"";
 $("aiFreshness").textContent=(fresh?"Recent worker observation":"Stale or unverified worker observation")+" · "+time(h.timestamp);
 $("aiFreshness").className=fresh?"empty":"empty caution";
 const a=finite(d.long_score)&&Number(d.long_score)>=0?Number(d.long_score):null,b=finite(d.short_score)&&Number(d.short_score)>=0?Number(d.short_score):null;
 const track=$("aiScoreTrack");track.replaceChildren();
 if(a!==null&&b!==null&&a+b>0){
  const progress=el("progress",undefined,"ai-score-progress");progress.max=a+b;progress.value=a;progress.setAttribute("aria-label","Long share of directional scores");track.append(progress);
 }else track.append(el("span","No directional score balance available","empty"));
 $("aiLongScore").textContent="LONG "+aiNumber(a)+(a!==null&&b!==null&&a+b>0?" · "+(100*a/(a+b)).toFixed(1)+"%":"");
 $("aiShortScore").textContent="SHORT "+aiNumber(b)+(a!==null&&b!==null&&a+b>0?" · "+(100*b/(a+b)).toFixed(1)+"%":"");
 const cards=[["Market regime",aiLabel(reg.regime)],["Volatility",aiLabel(reg.volatility)],["Trend bias",aiLabel(reg.trend_bias)],["Long / short rules",fmt(d.long_votes)+" / "+fmt(d.short_votes)],["Conflicts",fmt(d.conflicting_rules)],["Evaluable rules",fmt(h.coverage?.evaluable_rules)+" / 50"]];
 $("aiRegimeCards").replaceChildren(...cards.map(([k,v])=>{const n=el("div",undefined,"ai-regime-card");n.append(el("small",k),el("strong",v));return n}));
 const groups=["LONG","SHORT","CONFLICT"],rules=$("aiActiveRules");rules.replaceChildren();
 for(const k of groups){
  const list=Array.isArray(d.votes?.[k])?d.votes[k]:null,box=el("div",undefined,"ai-rule-group");
  box.append(el("h3",k+" · "+fmt(list?.length),k==="LONG"?"gain":k==="SHORT"?"loss":"caution"));
  if(!list?.length)box.append(el("p",list?"No active rules":"Unavailable","empty"));
  else for(const r of list){const line=el("div",undefined,"ai-rule-row");line.append(el("strong",r.id+" · "+human(r.name)),el("small",(r.frames||[]).join(" / ")));box.append(line)}
  rules.append(box);
 }
 const families=Object.entries(d.family_scores||{}).map(([family,v])=>({family,long:v.LONG?.score,short:v.SHORT?.score}));
 table("aiFamilyScores",families,[["Family",r=>human(r.family)],["Long",r=>aiNumber(r.long)],["Short",r=>aiNumber(r.short)]]);
}
function aiEventContent(e,compact=false){
 const n=el("div",undefined,"ai-event-content");
 const fields=el("dl",undefined,"ai-event-fields");
 const facts=[["Journal state",aiLabel(e.status)],["Requested action",aiLabel(e.action)],["Exchange evidence",e.execution?human(e.execution):"Not linked / unavailable"]];
 if(e.type==="entry")facts.push(["Side",aiLabel(e.side)],["Model",fmt(e.model)],["Outcome",aiLabel(e.outcome)],["Net before funding",money(e.net,"USD")],["Planned size",fmt(e.size)],["Planned SL",fmt(e.sl)],["Planned TP",fmt(e.tp)]);
 else if(e.execution)facts.push(["Mutation action",aiLabel(e.executionAction)],["Attempt recorded",time(e.executionTime)]);
 for(const [k,v] of facts){fields.append(el("dt",k),el("dd",v))}
 n.append(fields);
 if(e.reason){n.append(el("h3","Recorded AI explanation"),el("p",e.reason,"ai-reason"))}
 else n.append(el("p","No recorded explanation available.","empty"));
 if(e.error)n.append(el("p","Recorded error: "+e.error,"caution"));
 if(e.rules?.length)n.append(el("p","New signals: "+e.rules.map(r=>r.id+" "+r.frame).join(", "),"empty"));
 return n;
}
function aiTimelineView(m){
 const events=aiEvents(m),latest=events[0],content=$("aiLatestContent");
 $("aiLatestTitle").textContent=latest?(latest.type==="entry"?"Entry evaluation":"Position management")+" · "+aiLabel(latest.action||latest.status):"No recorded AI activity";
 content.replaceChildren();
 if(latest)content.append(el("p",time(latest.created),"empty"),aiEventContent(latest,true));else content.append(el("p","Awaiting a journal observation.","empty"));
 const filtered=events.filter(e=>aiFilter==="all"||e.type===aiFilter);
 const key=JSON.stringify([m.symbol,aiFilter,filtered]);if(key===aiLastKey)return;aiLastKey=key;
 const list=$("aiTimeline");list.replaceChildren();
 if(!filtered.length){list.append(el("p","No recorded events in this filter.","empty"));return}
 for(const e of filtered){
  const detail=el("details",undefined,"ai-event");detail.open=aiExpanded.has(e.key);
  detail.addEventListener("toggle",()=>{if(detail.open)aiExpanded.add(e.key);else aiExpanded.delete(e.key)});
  const summary=el("summary"),meta=el("div",undefined,"ai-event-meta");
  meta.append(el("strong",(e.type==="entry"?"Entry":"Management")+" · "+aiLabel(e.action||e.status)),el("small",time(e.created)));
  const state=el("span",e.execution?"Exchange: "+human(e.execution):"Journal: "+aiLabel(e.status),"ai-event-state "+(e.execution==="verified"?"gain":e.status==="failed"?"caution":""));
  summary.append(meta,state);detail.append(summary,aiEventContent(e));list.append(detail);
 }
}
for(const b of document.querySelectorAll("[data-ai-filter]"))b.addEventListener("click",()=>{aiFilter=b.dataset.aiFilter;for(const x of document.querySelectorAll("[data-ai-filter]"))x.setAttribute("aria-pressed",String(x===b));const m=data?.markets?.find(x=>x.symbol===chosen);if(m)aiTimelineView(m)});


let labSelected=null,labMatrixKey="",labFamilyKey="";
const labLabels={LONG:"Long",SHORT:"Short",CONFLICT:"Conflict",inactive:"Inactive",no_vote_unverified:"No vote / unverified",stale_or_unavailable:"Stale / unavailable",deferred:"Deferred"};
const labClass=s=>({LONG:"lab-long",SHORT:"lab-short",CONFLICT:"lab-conflict",inactive:"lab-inactive",deferred:"lab-deferred"}[s]||"lab-unknown");
const labNum=v=>finite(v)?Number(v).toLocaleString(undefined,{maximumFractionDigits:2}):"—";
function labMarkets(){
 return (data?.markets||[]).map(m=>({symbol:m.symbol,lab:m.strategy_lab||{},regime:m.regime_performance||{},overlap:m.combination_intelligence?.overlap||{}}));
}
function labInspector(markets){
 const wrap=$("labDetails");wrap.replaceChildren();
 const market=markets.find(m=>(m.lab.rules||[]).some(r=>r.id===labSelected));
 const r=market?.lab.rules.find(x=>x.id===labSelected);
 if(!r){wrap.append(el("p","Choose a combination in the matrix.","empty"));return}
 const title=el("div",undefined,"lab-detail-head");title.append(el("h2",r.id+" · "+human(r.name)),el("span",labLabels[r.state]||"Unavailable","lab-state "+labClass(r.state)));wrap.append(title);
 const facts=el("dl",undefined,"ai-event-fields");
 for(const [k,v] of [["Market",market.symbol],["Family",human(r.family)],["Implementation",human(r.implementation)],["Configured timeframes",(r.frames||[]).join(" / ")||"—"],["Active vote timeframes",(r.active_frames||[]).join(" / ")||"—"],["Worker observation",market.lab.fresh?time(market.lab.observed):"Stale / unavailable"],["Missing dependency",r.missing_dependency||"—"]])facts.append(el("dt",k),el("dd",v));
 wrap.append(facts,el("h3","Required strategy inputs"));
 const inputs=el("div",undefined,"lab-inputs");
 for(const f of r.required_inputs||[])inputs.append(el("span",f));
 if(!inputs.children.length)inputs.append(el("p","No live rule inputs registered.","empty"));wrap.append(inputs);
 if(r.deferred_evidence){const e=r.deferred_evidence;wrap.append(el("h3","Deferred research"),el("p",human(e.stage)+" · "+human(e.status)+" · execution disabled","caution"))}
 wrap.append(el("h3","Fixed-horizon research · assumed 15 bps cost"));
 const horizon=el("div",undefined,"lab-horizons");
 for(const h of r.research||[]){
  const c=el("article",undefined,"lab-horizon");c.append(el("small",h.horizon_s/60+" min horizon"),el("strong",labNum(h.mean_net_bps)+" bps",finite(h.mean_net_bps)?Number(h.mean_net_bps)>=0?"gain":"loss":""),el("small",fmt(h.valid_samples)+" nonoverlapping samples"),el("small","Positive windows: "+percent(h.positive_rate)));horizon.append(c);
 }
 if(!horizon.children.length)horizon.append(el("p","Research unavailable.","empty"));wrap.append(horizon);
 const a=r.actual_cooccurrence;
 wrap.append(el("h3","Actual attributed trade associations"),el("p",a?fmt(a.closed_episodes)+" closed episodes · "+money(a.net_before_funding,"USD")+" net before funding · "+percent(a.win_rate_before_funding)+" winning episodes":"No attributed association reported.","empty"));
 const regimes=(market.regime.research||[]).filter(x=>x.level==="rule"&&x.id===r.id);
 if(regimes.length){
  wrap.append(el("h3","Observed regime breakdown"));const list=el("div",undefined,"lab-mini-list");
  for(const x of regimes.slice(0,18))list.append(el("p",human(x.regime)+" / "+human(x.volatility)+" · "+x.horizon_s/60+"m · "+fmt(x.valid_samples)+" samples · "+labNum(x.mean_net_bps)+" bps"));wrap.append(list)
 }
 const pairs=(market.overlap.pairs||[]).filter(p=>p.rules?.includes(r.id)).slice(0,8);
 if(pairs.length){wrap.append(el("h3","Frequently co-active combinations"));const list=el("div",undefined,"lab-mini-list");for(const p of pairs)list.append(el("p",p.rules.filter(i=>i!==r.id).join(" + ")+" · "+fmt(p.together)+" shared observations · "+labNum(100*p.jaccard)+"% Jaccard overlap"));wrap.append(list)}
 wrap.append(el("p","Research outcomes are unleveraged mark-price observations, not actual trades. Trade associations overlap and do not establish causal contribution. Required inputs are not a full condition specification.","empty"));
}
function labView(){
 const markets=labMarkets(),all=markets.flatMap(m=>m.lab.rules||[]);
 if(!labSelected||!all.some(r=>r.id===labSelected))labSelected=all[0]?.id||null;
 const families=[...new Set(all.map(r=>r.family))].sort(),familyKey=families.join("|"),family=$("labFamily");
 if(familyKey!==labFamilyKey){const old=family.value;family.replaceChildren(el("option","All families"));family.firstChild.value="all";for(const f of families){const o=el("option",human(f));o.value=f;family.append(o)}family.value=families.includes(old)?old:"all";labFamilyKey=familyKey}
 const q=$("labSearch").value.trim().toLowerCase(),state=$("labState").value;
 const match=r=>(family.value==="all"||r.family===family.value)&&(state==="all"||r.state===state)&&(!q||(r.id+" "+r.name+" "+human(r.name)).toLowerCase().includes(q));
 const available=markets.length===2&&markets.every(m=>m.lab.fresh&&finite(m.lab.evaluable_rules))?markets.reduce((n,m)=>n+Number(m.lab.evaluable_rules),0):null;
 $("labSummary").textContent=all.length+" registered · "+all.filter(match).length+" shown · "+fmt(available)+" evaluable (fresh)";
 const key=JSON.stringify([labSelected,q,state,family.value,all.map(r=>[r.id,r.name,r.family,r.state])]);
 if(key!==labMatrixKey){
  labMatrixKey=key;const wrap=$("labMatrix");wrap.replaceChildren();
  for(const m of markets){
   const rows=(m.lab.rules||[]).filter(match),section=el("div",undefined,"lab-market");
   section.append(el("h3",(m.symbol==="BTCUSD"?"Bitcoin":"Gold")+" · "+rows.length+" / 50"));
   const grid=el("div",undefined,"lab-matrix");
   for(const r of rows){const b=el("button",r.id,"lab-cell "+labClass(r.state));b.setAttribute("aria-pressed",String(r.id===labSelected));b.setAttribute("aria-label",r.id+" "+human(r.name)+" "+(labLabels[r.state]||"Unavailable"));b.title=r.id+" · "+human(r.name)+" · "+(labLabels[r.state]||"Unavailable");b.addEventListener("click",()=>{labSelected=r.id;labView();const target=Array.from($("labMatrix").querySelectorAll("button")).find(n=>n.textContent===r.id);target?.focus({preventScroll:true})});grid.append(b)}
   if(!rows.length)grid.append(el("p","No matching combinations","empty"));section.append(grid);wrap.append(section)
  }
 }
 labInspector(markets);
}
for(const k of ["labSearch","labFamily","labState"])$(k).addEventListener(k==="labSearch"?"input":"change",labView);
$("labReset").addEventListener("click",()=>{$("labSearch").value="";$("labFamily").value="all";$("labState").value="all";labView()});


let inspectorMarket=null,inspectorChoice="";
const episodeKey=e=>JSON.stringify([e.opened,e.closed,e.decision_id??null,e.direction]);
function boundaryFill(fills,when,side,currency,closing){
 const matches=(fills||[]).filter(f=>f&&f.created_at===when);
 if(matches.length!==1)return null;
 const f=matches[0],after=f.new_position?.size;
 if(f.side!==side||f.settling_asset_symbol!==currency||!finite(f.price)||Number(f.price)<=0||!finite(after))return null;
 if(closing?Number(after)!==0:(side==="buy"?Number(after)<=0:Number(after)>=0))return null;
 return f;
}
function inspectorView(m){
 const p=m.performance||{},currency=p.currency||"",rows=(p.recent_episodes||[]).slice().reverse(),select=$("inspectorEpisode"),content=$("inspectorContent");
 if(inspectorMarket!==m.symbol){inspectorMarket=m.symbol;inspectorChoice=""}
 const keys=rows.map(episodeKey);
 if(!keys.includes(inspectorChoice))inspectorChoice=keys[0]||"";
 if(JSON.stringify(Array.from(select.options).map(o=>o.value))!==JSON.stringify(keys.length?keys:[""])){
  select.replaceChildren();
  if(!rows.length){const o=el("option","No reconciled positions");o.value="";select.append(o)}
  for(const e of rows){const o=el("option",fmt(e.closed)+" · "+human(e.direction)+" · "+money(e.net_before_funding,currency));o.value=episodeKey(e);select.append(o)}
 }
 select.disabled=!rows.length;select.value=inspectorChoice;
 const e=rows.find(x=>episodeKey(x)===inspectorChoice);
 if(!e){$("inspectorStatus").textContent="No reconciled closed position available · "+human(p.status);content.replaceChildren();return}
 const d=e.decision_id?(m.decisions||[]).find(x=>x.id===e.decision_id):null;
 const reviews=e.decision_id?(m.decision_review?.recent||[]).filter(x=>x.id===e.decision_id):[];
 const r=reviews.length===1?reviews[0]:null,plan=d?.result||{};
 const openingSide=e.direction==="LONG"?"buy":e.direction==="SHORT"?"sell":null;
 const open=openingSide?boundaryFill(m.fills,e.opened,openingSide,currency,false):null;
 const close=openingSide?boundaryFill(m.fills,e.closed,openingSide==="buy"?"sell":"buy",currency,true):null;
 $("inspectorStatus").textContent=m.symbol+" · "+human(e.attribution)+" · "+fmt(e.fills)+" reconciled fills";
 const cards=el("div",undefined,"inspector-cards");
 for(const [label,value,cls] of [["Net before funding",money(e.net_before_funding,currency),finite(e.net_before_funding)?Number(e.net_before_funding)>0?"gain":Number(e.net_before_funding)<0?"loss":"neutral":"neutral"],["Gross P&L",money(e.gross_pnl,currency),"neutral"],["Commissions",money(e.fees,currency),"neutral"]]){
  const n=el("div",undefined,"metric");n.append(el("small",label),el("strong",value,cls));cards.append(n);
 }
 const layout=el("div",undefined,"inspector-grid");
 function fields(title,pairs){
  const panel=el("div",undefined,"inspector-block"),dl=el("dl",undefined,"inspector-fields");panel.append(el("h3",title));
  for(const [label,value] of pairs){dl.append(el("dt",label),el("dd",value))}panel.append(dl);layout.append(panel);
 }
 fields("Position lifecycle",[["Direction",human(e.direction)],["Opened",fmt(e.opened)],["Closed",fmt(e.closed)],["First observed entry fill",fmt(open?.price)],["Final observed exit fill",fmt(close?.price)],["Entry order average (review)",fmt(r?.average_fill_price)],["Reported funding (unverified)",money(e.reported_funding,currency)]]);
 fields("Recorded AI plan",[["Decision ID",fmt(e.decision_id)],["Model",fmt(d?.model??r?.model)],["Action",human(plan.action??r?.action)],["Reference entry",fmt(plan.entry_reference)],["Planned stop",fmt(plan.stop_loss)],["Planned target",fmt(plan.take_profit)],["Planned reward/risk",fmt(r?.planned_reward_risk)],["Entry deviation (bps)",fmt(r?.entry_deviation_bps)]]);
 const reasoning=el("div",undefined,"inspector-block");reasoning.append(el("h3","Recorded explanation"),el("p",d?.result?.reason??r?.reason??"No linked explanation in the available decision archive."),el("h3","Associated strategy triggers"));
 const rules=el("div",undefined,"inspector-rules");
 for(const id of e.active_rules||[])rules.append(el("span",id));
 if(!rules.childElementCount)rules.append(el("p","No attributed rules available.","empty"));reasoning.append(rules);
 content.replaceChildren(cards,layout,reasoning,el("p","First and final fill prices are shown only when a unique matching boundary record is available in the recent fill window; they are not weighted episode prices. Planned levels are not verified exit triggers.","empty"));
}
$("inspectorEpisode").addEventListener("change",()=>{inspectorChoice=$("inspectorEpisode").value;const m=data?.markets.find(x=>x.symbol===chosen);if(m)inspectorView(m)});

function historyView(m){
 const query=$("historyQuery").value.trim().toLowerCase(),side=$("historySide").value;
 const orderFields=r=>[r.client_id,r.status,r.exchange?.status,r.intent?.side,r.intent?.size,r.exchange?.filled_size,r.exchange?.order?.average_fill_price,r.intent?.stop_loss,r.intent?.take_profit];
 const fillFields=r=>[r.id,r.order_id,r.created_at,r.side,r.size,r.price,r.commission,r.settling_asset_symbol];
 const match=(fields,s)=> (side==="all"||String(s??"").toLowerCase()===side)&&(!query||fields.some(v=>v!=null&&String(v).toLowerCase().replaceAll("_"," ").includes(query.replaceAll("_"," "))));
 const rawOrders=Array.isArray(m.orders)?m.orders.filter(Boolean):null,rawFills=Array.isArray(m.fills)?m.fills.filter(Boolean):null;
 const orders=rawOrders?.filter(r=>match(orderFields(r),r.intent?.side))??null;
 const fills=rawFills?.filter(r=>match(fillFields(r),r.side))??null;
 const count=(name,rows,total)=>total===null?name+" unavailable":name+" "+rows.length+" of "+total.length;
 $("historyCounts").textContent=m.symbol+" · "+count("Orders",orders,rawOrders)+" · "+count("Fills",fills,rawFills);
 table("orders",orders,[["Client ID",r=>fmt(r.client_id)],["Submission",r=>human(r.status)],["Exchange state",r=>human(r.exchange?.status)],["Side",r=>r.intent?.side],["Size",r=>r.intent?.size],["Filled",r=>r.exchange?.filled_size],["Fill price",r=>r.exchange?.order?.average_fill_price],["SL",r=>r.intent?.stop_loss],["TP",r=>r.intent?.take_profit]]);
 table("fills",fills,[["Time",r=>r.created_at],["Fill ID",r=>r.id],["Side",r=>r.side],["Size",r=>r.size],["Price",r=>r.price],["Fee",r=>r.commission],["Asset",r=>r.settling_asset_symbol],["Position realized P&L*",r=>r.new_position?.realized_pnl]]);
 $("fills").append(el("p","* Exchange position metadata may be cumulative; not summed as per-trade profit.","empty"));
 if(rawOrders?.length&&!orders.length)empty("orders","No orders match these filters");
 if(rawFills?.length&&!fills.length)empty("fills","No fills match these filters");
}
function refreshHistoryView(){
 const market=data?.markets.find(m=>m.symbol===chosen);
 if(market)historyView(market);
}
$("historyQuery").addEventListener("input",refreshHistoryView);
$("historySide").addEventListener("change",refreshHistoryView);
$("historyReset").addEventListener("click",()=>{$("historyQuery").value="";$("historySide").value="all";refreshHistoryView()});


function learnLessonView(m){
 const ol=m.outcome_learning||{},all=ol.lessons||[],filter=$("learnOutcomeFilter").value;
 const rows=all.filter(r=>filter==="all"||r.outcome===filter);
 $("learnFilterCount").textContent=rows.length+" of "+all.length+" recent lessons shown · followups below remain unfiltered";
 table("learningRows",rows,[["Decision",r=>fmt(r.decision_id).slice(0,12)],["Outcome",r=>human(r.outcome)],["Net before funding",r=>fmt(r.net_before_funding)],["Entry deviation bps",r=>fmt(r.entry_evidence?.entry_deviation_bps)],["Observed exit gap bps",r=>fmt(r.exit_evidence?.observed_favorable_gap_bps)]]);
 if(all.length&&!rows.length)empty("learningRows","No lessons match this outcome");
}
function learnIntelligence(m){
 const ol=m.outcome_learning||{},lm=m.learning_memory||{},mc=m.memory_comparison||{},lessons=ol.lessons||[];
 const counts=["win","loss","breakeven"].map(k=>({status:k,count:lessons.filter(r=>r.outcome===k).length}));
 const unknown=lessons.length-counts.reduce((sum,x)=>sum+x.count,0);
 if(unknown)counts.push({status:"unknown",count:unknown});
 const follow=ol.followup_counts||{},validated=Array.isArray(lm.statistically_supported_lessons)?lm.statistically_supported_lessons.length:null;
 $("learnSummary").textContent=m.symbol+" · Learning journal: "+human(ol.status)+" · Memory: "+human(lm.status)+" · "+(lm.model_feedback_enabled===false?"Automatic model feedback disabled":"Model feedback status unavailable");
 metrics([["Recorded lessons",fmt(ol.lesson_count),"Journal total"],["Observed followups",fmt(follow.observed??(ol.status==="observed"?0:null)),"Journal total · all timing classes"],["Process categories",fmt(lm.process_observations?.length),"Reported observations"],["Validated lessons",fmt(validated),"Statistical evidence only"]],"learnMetrics");
 const dist=$("learnDistribution");
 if(!lessons.length)empty("learnDistribution","No recorded lessons in the recent window");
 else{
  const track=el("div",undefined,"learn-distribution"),legend=el("div",undefined,"legend");
  track.setAttribute("role","img");track.setAttribute("aria-label",counts.map(x=>x.status+" "+x.count).join(", "));
  for(const x of counts){const cls=x.status==="win"?"gain":x.status==="loss"?"loss":"neutral";if(x.count){const part=el("div",undefined,"learn-segment "+cls);part.style.flexGrow=String(x.count);track.append(part)}legend.append(el("span",human(x.status)+" "+x.count,cls))}
  dist.replaceChildren(track,legend);
 }
 const patterns=(lm.process_observations||[]).filter(x=>Number.isInteger(x.count)&&x.count>0).slice().sort((a,b)=>b.count-a.count);
 if(!patterns.length)empty("learnPatterns","No process observations reported");
 else{
  const max=patterns[0].count;
  $("learnPatterns").replaceChildren(...patterns.map(x=>{const row=el("div",undefined,"learn-pattern"),head=el("div",undefined,"learn-pattern-head"),bar=el("progress");head.append(el("strong",human(x.kind)),el("strong",x.count));bar.max=max;bar.value=x.count;bar.setAttribute("aria-label",human(x.kind)+" "+x.count+" observations");row.append(head,bar,el("small",human(x.evidence_grade)+" · "+fmt(x.scope)));return row}));
 }
 function horizonLabel(s){return finite(s)?Number(s)/60+" min":"Unknown horizon"}
 function bps(v){return finite(v)?Number(v).toFixed(2)+" bps":"—"}
 function signedBar(label,value,max){
  const row=el("div",undefined,"learn-signed"),track=el("div",undefined,"learn-signed-track"),bar=el("span",undefined,Number(value)<0?"loss":"gain");
  row.append(el("span",label),track,el("strong",bps(value),finite(value)?Number(value)>0?"gain":Number(value)<0?"loss":"neutral":"neutral"));
  if(finite(value)){bar.style.width=(Math.abs(Number(value))/max*50)+"%";bar.style.left=Number(value)<0?(50-Math.abs(Number(value))/max*50)+"%":"50%";track.append(bar)}
  track.setAttribute("aria-hidden","true");return row;
 }
 const hy=lm.hypotheses||[],hyMax=Math.max(1,...hy.filter(x=>finite(x.mean_gross_directional_bps)).map(x=>Math.abs(Number(x.mean_gross_directional_bps))));
 if(!hy.length)empty("learnHypotheses","No hypothesis data available");
 else $("learnHypotheses").replaceChildren(...hy.map(x=>{const card=el("div",undefined,"learn-horizon");card.append(el("strong",horizonLabel(x.horizon_s)),el("small",fmt(x.prospective_nonoverlap_samples)+" prospective samples · "+human(x.evidence_grade)),signedBar("Mean gross",x.mean_gross_directional_bps,hyMax),el("small","Positive "+fmt(x.positive_count)+" · Negative "+fmt(x.negative_count)));return card}));
 const pairs=mc.horizons||[],pairMax=Math.max(1,...pairs.flatMap(x=>[x.mean_baseline_net_bps,x.mean_alternative_net_bps]).filter(finite).map(v=>Math.abs(Number(v))));
 if(!pairs.length)empty("learnComparison","No prospective comparison data available");
 else $("learnComparison").replaceChildren(...pairs.map(x=>{const card=el("div",undefined,"learn-horizon");card.append(el("strong",horizonLabel(x.horizon_s)),el("small",fmt(x.observed_pairs)+" observed pairs · "+fmt(x.disagreements)+" disagreements"),signedBar("Baseline",x.mean_baseline_net_bps,pairMax),signedBar("Proxy",x.mean_alternative_net_bps,pairMax),el("small","Mean paired difference: "+bps(x.mean_difference_bps)));return card}));
 learnLessonView(m);
}
$("learnOutcomeFilter").addEventListener("change",()=>{const m=data?.markets.find(x=>x.symbol===chosen);if(m)learnLessonView(m)});

function render(){
 if(!data)return;
 overviewView();
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
 performanceView(m);forwardView(m);aiEvidence(m);aiTimelineView(m);labView();
 const dr=m.deferred_research||{};
 $("deferredNote").textContent="Independent data and experimental frameworks · "+fmt(dr.rules?.length)+" deferred candidates";
 table("deferredRows",dr.rules||[],[["Rule",r=>r.id],["Stage",r=>human(r.stage)],["Evidence",r=>human(r.status)],["Source",r=>human(r.source_status)],["Consensus",r=>human(r.consensus_status)],["Execution",r=>r.execution_enabled?"Enabled":"Not enabled"]]);
 const referencePositioning=dr.positioning||{}, liq=referencePositioning.liquidations||{}, q=referencePositioning.latest||{};
 $("deferredFeed").textContent=m.symbol==="BTCUSD"?"Reference positioning: "+human(referencePositioning.status)+" · OI BTC "+fmt(q.open_interest_btc_both_sides)+" · indicative funding % "+fmt(q.indicative_funding_percent)+" · liquidation connection "+human(liq.status)+" · recorded batches "+fmt(liq.batches)+" · completeness unverified":"Official release probe: "+fmt(dr.economic?.last_probe_epoch?time(dr.economic.last_probe_epoch):null)+" · G25 calendar "+human(dr.reopening?.calendar_connection)+" · trade feed "+human(dr.reopening?.licensed_trade_feed);
 const of=m.overlap_forward||{},ofl=of.latest||{};
 $("overlapForwardNote").textContent=human(of.status)+" · "+human(of.validation)+" · "+(ofl.score?ofl.score.baseline_direction+" vs "+ofl.score.research_direction:"Awaiting eligible packet")+" · "+fmt(of.additional_ai_calls)+" additional AI calls";
 table("overlapForwardRows",of.horizons||[],[["Horizon min",r=>fmt(r.horizon_s/60)],["Pending",r=>fmt(r.counts?.pending||0)],["Overlap excluded",r=>fmt(r.counts?.overlap||0)],["Missing",r=>fmt(r.counts?.missing_candles||0)],["Observed",r=>fmt(r.observed_pairs)],["Disagreements",r=>fmt(r.disagreements)],["Original net bps",r=>fmt(r.mean_baseline_net_bps)],["Adjusted net bps",r=>fmt(r.mean_alternative_net_bps)],["Difference bps",r=>fmt(r.mean_difference_bps)],["Disagreement difference",r=>fmt(r.disagreement_mean_difference_bps)]]);
 const oc=m.overlap_confidence||{},olc=oc.latest||{},orc=oc.replay_counts||{};
 $("overlapConfidenceNote").textContent=human(oc.status)+" · "+human(olc.status)+" · "+fmt(olc.history_snapshots)+" prior sampled snapshots · "+fmt(olc.discounted_rule_count)+" discounted overlapping rule contributions · "+fmt(orc.direction_changes)+" direction changes in "+fmt(orc.evaluated)+" retrospective comparisons";
 table("overlapConfidenceScores",olc.status==="observed"?[{kind:"Original",side:olc.baseline_direction,scores:olc.baseline_scores,balance:olc.baseline_balance},{kind:"Research",side:olc.research_direction,scores:olc.research_scores,balance:olc.research_balance}]:[],[["Variant",r=>r.kind],["Direction",r=>r.side],["Long score",r=>fmt(r.scores.LONG)],["Short score",r=>fmt(r.scores.SHORT)],["Balance %",r=>r.balance==null?"—":fmt(100*r.balance)]]);
 table("overlapConfidenceClusters",["LONG","SHORT"].flatMap(s=>(olc.clusters?.[s]||[]).map(r=>({...r,side:s}))),[["Side",r=>r.side],["Rules",r=>r.rules.join(" + ")],["Original contribution",r=>fmt(r.original_contribution)],["Retained",r=>fmt(r.retained_contribution)]]);
 table("overlapConfidenceReplay",(oc.replay||[]).slice().reverse(),[["Observation",r=>new Date(r.as_of*1000).toLocaleString()],["Status",r=>human(r.status)],["Original",r=>r.baseline_direction||"—"],["Research",r=>r.research_direction||"—"],["Changed",r=>r.direction_changed==null?"—":r.direction_changed?"Yes":"No"],["Discounted",r=>fmt(r.discounted_rule_count)]]);
 const ci=m.combination_intelligence||{},co=ci.overlap||{},cj=ci.joint_research||{};
 $("combinationNote").textContent=human(ci.status)+" · "+fmt(co.sampled_packets)+" sampled snapshots · "+fmt(co.pair_count)+" co-active pairs · "+fmt(cj.joint_cohorts)+" shared-quote cohorts · descriptive only";
 table("combinationPairs",(co.pairs||[]).slice(0,30),[["Rules",r=>r.rules.join(" + ")],["Families",r=>r.families.join(" / ")],["Together",r=>fmt(r.together)],["Agree",r=>fmt(r.same_direction)],["Oppose",r=>fmt(r.opposed_direction)],["Conflict",r=>fmt(r.conflict_involved)],["Overlap %",r=>fmt(100*r.jaccard)]]);
 table("combinationJoint",(cj.pair_horizons||[]).slice(0,30),[["Rules",r=>r.rules.join(" + ")],["Horizon min",r=>fmt(r.horizon_s/60)],["Nonoverlap samples",r=>fmt(r.valid_nonoverlap_samples)],["Mean net bps",r=>fmt(r.mean_net_bps)],["Positive %",r=>r.positive_rate==null?"—":fmt(100*r.positive_rate)]]);
 const rp=m.regime_performance||{};
 $("regimePerfNote").textContent=human(rp.status)+" · Regimes: "+(rp.observed_regimes||[]).join(", ")+" · Volatility: "+(rp.observed_volatility||[]).join(", ")+" · Descriptive only";
 table("regimePerfCoverage",rp.coverage||[],[["Regime",r=>human(r.regime)],["Volatility",r=>human(r.volatility)],["Status",r=>human(r.status)],["Raw records",r=>fmt(r.count)]]);
 const regimeCols=[["Rule/family",r=>human(r.id)],["Regime",r=>human(r.regime)],["Volatility",r=>human(r.volatility)],["Horizon min",r=>fmt(r.horizon_s/60)],["Nonoverlap samples",r=>fmt(r.valid_samples)],["Mean net bps",r=>fmt(r.mean_net_bps)],["Positive %",r=>r.positive_rate==null?"—":fmt(100*r.positive_rate)]];
 table("regimePerfFamilies",(rp.research||[]).filter(r=>r.level==="family"),regimeCols);
 table("regimePerfRules",(rp.research||[]).filter(r=>r.level==="rule"),regimeCols);
 table("regimePerfActual",rp.actual||[],[["Regime",r=>human(r.regime)],["Volatility",r=>human(r.volatility)],["Closed trades",r=>fmt(r.closed_episodes)],["Net before funding",r=>fmt(r.net_before_funding)]]);
 const se=m.strategy_evidence||{};
 $("strategyEvidenceNote").textContent=human(se.status)+" · "+fmt(se.implemented)+" implemented · "+fmt(se.deferred)+" deferred · assumed research cost "+fmt(se.assumed_cost_bps)+" bps. Associations are not causal. Research is not executed P&L.";
 table("strategySets",se.exact_entry_rule_sets||[],[["Entry rules",r=>r.rules.join(", ")],["Closed",r=>fmt(r.closed_episodes)],["Net before funding",r=>money(r.net_before_funding,m.performance?.currency||"USD")]]);
 table("strategyEvidenceRows",(se.rules||[]).map(r=>({...r,h:r.research.find(h=>h.horizon_s===900)||{}})),[["Rule",r=>r.id+" "+human(r.name)],["Family",r=>human(r.family)],["Implementation",r=>human(r.implementation)],["Missing dependency",r=>r.missing_dependency||"—"],["Actual associations",r=>fmt(r.actual_cooccurrence?.closed_episodes)],["Research samples",r=>fmt(r.h.valid_samples)],["Mean net bps",r=>fmt(r.h.mean_net_bps)],["Positive rate",r=>percent(r.h.positive_rate)]]);

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
 const tpv=m.target_amendment_preview||{};
 $("targetPreview").textContent="TP amendment research: "+human(tpv.status)+" · existing target "+fmt(tpv.target_price)+" · unchanged stop "+fmt(tpv.stop_price)+" · single-leg amendment path available; see manual exchange evidence and autonomous attempts.";
 const eg=m.exit_geometry||{};
 $("exitGeometry").textContent="Exit evidence: "+human(eg.status)+" · Mark to stop "+fmt(eg.mark_to_stop_bps)+" bps · Mark to target "+fmt(eg.mark_to_target_bps)+" bps · Remaining distance ratio "+fmt(eg.remaining_target_to_stop_distance_ratio)+" · Observed trade peak minus mark "+fmt(eg.observed_excursion?.observed_trade_peak_minus_current_mark_bps)+" bps (mixed price basis, not exact giveback) · Consensus "+human(eg.direction_consensus_relation);
 $("openExcursion").textContent="Open position: "+human(ox.status)+(ox.mfe_bps==null?"":" · MFE "+fmt(ox.mfe_bps)+" bps · MAE "+fmt(ox.mae_bps)+" bps · Mark return "+fmt(ox.current_mark_return_bps)+" bps · Interior coverage "+(ox.coverage==null?"—":fmt(ox.coverage*100)+"%"));
 const ex=m.trade_excursions||{};
 $("excursionNote").textContent="Observed lower bounds from completed interior candles; boundary candles excluded. Peak gap is descriptive, not missed executable profit. Capture is an upper bound. "+human(ex.status);
 table("excursionRows",(ex.episodes||[]).slice().reverse(),[["Closed",r=>r.closed],["Direction",r=>r.direction],["MFE bps",r=>fmt(r.mfe_bps)],["MAE bps",r=>fmt(r.mae_bps)],["Weighted exit bps",r=>fmt(r.gross_weighted_exit_return_bps)],["Observed peak gap bps",r=>fmt(r.observed_favorable_gap_bps)],["Capture upper bound",r=>r.observed_capture_upper_bound_pct==null?"—":fmt(r.observed_capture_upper_bound_pct)+"%"],["Coverage",r=>r.coverage==null?"—":fmt(r.coverage*100)+"%"],["Evidence",r=>human(r.status)]]);
 const mr=m.management_report||{};
 $("managementRuntime").textContent="Management: "+(mr.enabled===true?"Enabled":mr.enabled===false?"Disabled":"Unverified")+" · "+human(mr.runtime_status)+" · Latest: "+human(mr.latest?.status)+" "+human(mr.latest?.action);
 bars("managementEvaluations",Object.entries(mr.evaluations||{}).map(([status,count])=>({status,count})));
 bars("managementActions",Object.entries(mr.actions||{}).map(([status,count])=>({status,count})));
 $("managementLatency").textContent="Median provider response: "+(mr.median_response_ms==null?"Unavailable":fmt(mr.median_response_ms/1000)+" s")+" · "+fmt(mr.latency_samples)+" timed responses";
 table("managementAttemptTable",mr.autonomous_attempts||[],[["Action",r=>human(r.action)],["Status",r=>human(r.status)],["Count",r=>fmt(r.count)]]);
 table("manualManagementEvidence",mr.manual_exchange_evidence||[],[["Test",r=>human(r.kind)],["Status",r=>human(r.status)],["Order ID",r=>r.order_id],["Trigger / remaining",r=>r.trigger??r.remaining_contracts]]);
 const managementCompat=m.management_compat||{};
 $("managementNote").textContent="Status: "+human(managementCompat.status)+" · Amendment: "+human(managementCompat.amendment)+" · Close: "+human(managementCompat.reduce_only_close)+" · Historical fills: "+fmt(managementCompat.historical_fills);
 bars("managementCounts",Object.entries(managementCompat.fill_transitions||{}).map(([status,count])=>({status,count})));
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
 const ol=m.outcome_learning||{};
 $("learningNote").textContent=human(ol.status)+" · "+fmt(ol.lesson_count)+" recorded closed-trade lessons · observation only";
 learnIntelligence(m);
 table("learningFollowups",ol.followups||[],[["Decision",r=>r.decision_id.slice(0,12)],["Horizon min",r=>fmt(r.horizon_s/60)],["Timing",r=>human(r.timing)],["Status",r=>human(r.status)],["Directional return bps",r=>fmt(r.evidence?.gross_directional_price_return_bps)]]);
 const mc=m.memory_comparison||{};
 $("memoryCompareNote").textContent=human(mc.status)+" · "+human(mc.validation)+" · "+fmt(mc.additional_ai_calls)+" extra AI requests · "+(mc.latest?human(mc.latest.reason):"Awaiting eligible new proposal");
 table("memoryCompareRows",mc.horizons||[],[["Horizon min",r=>fmt(r.horizon_s/60)],["Observed pairs",r=>fmt(r.observed_pairs)],["Disagreements",r=>fmt(r.disagreements)],["Baseline net bps",r=>fmt(r.mean_baseline_net_bps)],["Proxy net bps",r=>fmt(r.mean_alternative_net_bps)],["Mean difference bps",r=>fmt(r.mean_difference_bps)]]);
 const lm=m.learning_memory||{};
 $("memoryNote").textContent=human(lm.status)+" · "+fmt(lm.verified_observations?.length)+" observations · "+fmt(lm.process_observations?.length)+" process categories · "+fmt(lm.statistically_supported_lessons?.length)+" validated trading lessons";
 table("memoryFacts",lm.verified_observations||[],[["Observation",r=>human(r.kind)],["Count",r=>fmt(r.count??1)],["Net before funding",r=>fmt(r.net_before_funding)],["Evidence",r=>human(r.evidence_grade)]]);
 table("memoryIssues",lm.process_observations||[],[["Process finding",r=>human(r.kind)],["Count",r=>fmt(r.count)],["Evidence",r=>human(r.evidence_grade)],["Scope",r=>r.scope]]);
 table("memoryHypotheses",lm.hypotheses||[],[["Horizon min",r=>fmt(r.horizon_s/60)],["Prospective samples",r=>fmt(r.prospective_nonoverlap_samples)],["Mean gross bps",r=>fmt(r.mean_gross_directional_bps)],["Status",r=>human(r.evidence_grade)]]);
 const xp=m.exit_cost_preview||{};
 $("exitCostNote").textContent=human(xp.status)+" · Break-even exit fill "+fmt(xp.break_even_exit_fill_price)+" · Favorable move "+fmt(xp.break_even_favorable_move_bps)+" bps · Assumed one-way fee "+fmt(xp.one_way_assumed_fee_bps)+" bps · Remaining contracts "+fmt(xp.remaining_contracts);
 table("exitCostRows",["mark","target","stop"].filter(k=>xp[k+"_scenario"]).map(k=>({label:human(k),...xp[k+"_scenario"]})),[["Scenario",r=>r.label],["Hypothetical fill",r=>fmt(r.assumed_exit_fill_price)],["Gross bps",r=>fmt(r.gross_return_bps)],["Commission bps",r=>fmt(r.estimated_commission_bps)],["Net before funding bps",r=>fmt(r.net_before_funding_bps)],["Illustrative half-spread net bps",r=>fmt(r.illustrative_adverse_half_spread?.net_before_funding_bps)]]);
 const ec=m.execution_cost||{},ef=ec.fill_commission||{},es=ec.spread||{},eu=ec.funding||{};
 $("costNote").textContent=human(ec.status)+" · "+fmt(ef.samples)+" observed fee fills · "+fmt(ef.turnover_weighted_one_way_fee_bps)+" bps one-way weighted commission · "+fmt(es.median_full_spread_bps)+" bps median full spread ("+fmt(es.samples)+" recent quotes) · funding fields "+fmt(eu.reported_field_present)+"/"+fmt(eu.recent_closed_episodes)+"; settlement unverified";
 table("costClosed",["all_reconciled","recover_attributed","unattributed"].map(k=>({label:human(k),...(ec[k]||{})})),[["Scope",r=>r.label],["Closed",r=>fmt(r.closed_episodes)],["Gross",r=>fmt(r.gross_pnl)],["Commission",r=>fmt(r.commission)],["Net before funding",r=>fmt(r.net_before_funding)],["Fee / positive gross %",r=>fmt(r.commission_pct_of_positive_aggregate_gross)]]);
 table("costEntries",ec.entry_samples||[],[["Decision",r=>r.decision_id.slice(0,12)],["Reference deviation bps",r=>fmt(r.reference_deviation_bps)],["Decision full spread bps",r=>fmt(r.decision_full_spread_bps)],["Submission full spread bps",r=>fmt(r.submission_full_spread_bps)],["Book-to-fill bps",r=>fmt(r.submission_book_to_fill_bps)]]);
 const dq=m.decision_quality||{};
 $("decisionQualityNote").textContent="Closed Recover episodes: "+fmt(dq.closed_recover_episodes)+" · Filled decision samples: "+fmt(dq.filled_decision_samples)+" · Complete attributed excursions: "+fmt(dq.complete_attributed_excursion_samples)+" · "+human(dq.closed_outcome_evidence);
 table("qualityRows",dq.findings||[],[["Finding",r=>human(r.finding)],["Count",r=>fmt(r.count)],["Evidence",r=>r.evidence],["Scope",r=>r.scope]]);
 const sa=m.submission_audit||{};
 $("submissionNote").textContent="Status: "+human(sa.status)+" · Misaligned brackets: "+fmt(sa.misaligned_brackets)+" · Unknown alignment: "+fmt(sa.unknown_tick_alignment);
 table("submissionRows",sa.recent?.slice().reverse()??null,[["Submission",r=>human(r.status)],["Position at decision",r=>human(r.position_at_decision)],["Side",r=>r.side],["Tick alignment",r=>r.tick_alignment===null?"Unknown":r.tick_alignment?"Aligned":"Misaligned"],["HTTP status",r=>r.http_status],["Exchange code",r=>r.exchange_code]]);
 const hs=m.historical_submission_evidence||{};
 $("historicalSubmissionNote").textContent=human(hs.status)+" · "+fmt(hs.unknown_count)+" unresolved · "+fmt(hs.snapshot_window_count)+" archived snapshots examined";
 table("historicalSubmissionRows",hs.rows||[],[["Client ID",r=>r.client_id.slice(0,12)],["Evidence",r=>human(r.classification)],["Original HTTP",r=>fmt(r.original_http_status)],["Not-found observation times",r=>fmt(r.distinct_not_found_observation_times)],["Latest lookup",r=>human(r.last_lookup_code)]]);
 historyView(m);inspectorView(m);
}
$("scopeRecover").addEventListener("click",()=>{scope="recover";render()});
$("scopeAccount").addEventListener("click",()=>{scope="account";render()});
for(const b of document.querySelectorAll("[data-symbol]"))b.addEventListener("click",()=>chooseMarket(b.dataset.symbol));
async function refresh(){if(busy)return;busy=true;try{const r=await fetch("/api/overview",{cache:"no-store"});if(!r.ok)throw Error();data=await r.json();document.dispatchEvent(new CustomEvent("recover:overview",{detail:data.markets.map(m=>m.chart_overlay).filter(Boolean)}));render();$("refresh").textContent="Updated "+time(data.generated)}catch{$("refresh").textContent="Refresh failed · retained data";$("warning").textContent="Dashboard connection unavailable. Previously displayed data may be stale."}finally{busy=false}}
refresh();setInterval(refresh,10000);