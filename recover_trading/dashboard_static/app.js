"use strict";
const $=id=>document.getElementById(id);
let chosen="BTCUSD", data=null, busy=false;
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
function metrics(values){$("metrics").replaceChildren(...values.map(([label,value,detail])=>{const box=el("div",undefined,"metric");box.append(el("small",label),el("strong",value),el("small",detail));return box}))}
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
function render(){
 if(!data)return;
 const m=data.markets.find(x=>x.symbol===chosen);if(!m)return;
 const snap=m.snapshot||{},h=m.heartbeat||{},wallets=snap.wallets,positions=snap.positions;
 const alerts=[];if(!h.timestamp)alerts.push("Worker heartbeat unavailable");else if(Date.now()/1000-h.timestamp>180)alerts.push("Worker observation older than 3 minutes");
 if(!m.availability.wallets)alerts.push("Wallet data unavailable");if(Object.keys(snap.errors||{}).length)alerts.push("Exchange observations incomplete");
 if(snap.observed&&Date.now()/1000-snap.observed>180)alerts.push("Position snapshot may be stale");
 if(h.status==="cycle_error")alerts.push("Latest cycle reported an error");
 $("warning").textContent=alerts.join(" • ");
 const sum=rows=>rows?.reduce((s,r)=>s+r.count,0)??null;
 metrics([["Market price",fmt(m.prices.at(-1)?.close),"Last recorded 5m close"],["Open positions",positions?.length??"—","Exchange observation"],["AI decisions",fmt(sum(m.decision_counts)),"Journal count"],["Order submissions",fmt(sum(m.order_counts)),"Not completed trades"],["Win rate","—","Attribution pending"],["Realized trade P&L","—","Attribution pending"]]);
 chart("price",m.prices.map(p=>[p.time,p.close]));
 const asset=wallets?.[0]?.asset_symbol;
 chart("walletChart",asset?m.wallet_history.map(p=>[p.observed,p.wallets.find(w=>w.asset_symbol===asset)?.balance]):[]);
 if(asset)$("walletChart").append(el("p","Chart asset: "+asset,"empty"));
 table("wallet",wallets??null,[["Asset",r=>r.asset_symbol],["Balance",r=>r.balance],["Available",r=>r.available_balance],["Position margin",r=>r.position_margin],["Order margin",r=>r.order_margin]]);
 $("brackets").textContent="Bracket evidence: "+human(snap.bracket_evidence)+" · Observed "+time(snap.observed)+" · Not a coverage guarantee.";
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
 table("decisions",m.availability.decisions?m.decisions:null,[["Time",r=>time(r.created)],["Model",r=>r.model],["Decision",r=>human(r.result?.action||r.status)],["Side",r=>r.result?.side],["Capital budget",r=>r.result?.capital_allocation],["Size",r=>r.result?.size],["SL",r=>r.result?.stop_loss],["TP",r=>r.result?.take_profit],["Signals",r=>r.signals.map(s=>s.id+" "+s.frame).join(", ")],["Reason",r=>r.result?.reason||r.result?.error]]);
 table("orders",m.orders,[["Client ID",r=>r.client_id.slice(0,12)],["Submission",r=>human(r.status)],["Exchange state",r=>human(r.exchange?.status)],["Side",r=>r.intent?.side],["Size",r=>r.intent?.size],["Filled",r=>r.exchange?.filled_size],["Fill price",r=>r.exchange?.order?.average_fill_price],["SL",r=>r.intent?.stop_loss],["TP",r=>r.intent?.take_profit]]);
 table("fills",m.fills?.filter(Boolean)??null,[["Time",r=>r.created_at],["Fill ID",r=>r.id],["Side",r=>r.side],["Size",r=>r.size],["Price",r=>r.price],["Fee",r=>r.commission],["Asset",r=>r.settling_asset_symbol],["Position realized P&L*",r=>r.new_position?.realized_pnl]]);
 $("fills").append(el("p","* Exchange position metadata may be cumulative; not summed as per-trade profit.","empty"));
}
for(const b of document.querySelectorAll("nav button"))b.addEventListener("click",()=>{chosen=b.dataset.symbol;for(const x of document.querySelectorAll("nav button"))x.setAttribute("aria-pressed",String(x===b));render()});
async function refresh(){if(busy)return;busy=true;try{const r=await fetch("/api/overview",{cache:"no-store"});if(!r.ok)throw Error();data=await r.json();render();$("refresh").textContent="Updated "+time(data.generated)}catch{$("refresh").textContent="Refresh failed · retained data";$("warning").textContent="Dashboard connection unavailable. Previously displayed data may be stale."}finally{busy=false}}
refresh();setInterval(refresh,10000);