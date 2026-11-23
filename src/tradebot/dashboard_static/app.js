"use strict";
// Read-only browser terminal. It never sends an order or exposes API credentials.
const byId = id => document.getElementById(id);
const text = (id, value) => { const el = byId(id); if(el) el.textContent = value == null ? "—" : String(value); };
const node = (tag, cls, value) => { const el = document.createElement(tag); if(cls) el.className = cls; if(value !== undefined) el.textContent = String(value); return el; };
const nfmt = (value, digits = 2) => {
  if(value == null || value === "") return "—";
  const v = Number(value);
  return Number.isFinite(v) ? new Intl.NumberFormat("en-US", {minimumFractionDigits:digits,maximumFractionDigits:digits}).format(v) : "—";
};
const timeLabel = iso => {
  if(!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("en-IN",{timeZone:"UTC",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",hour12:false}) + " UTC";
};
const ageLabel = seconds => seconds == null ? "Never reported" :
  seconds < 90 ? Math.round(seconds) + "s ago" : Math.round(seconds / 60) + "m ago";

// Equity evidence is a diagnostic only. Never enable an execution button
// based on this endpoint or infer authorization from a healthy status.
function renderEquityCheckpointRisk(data) {
  const banner=byId("equity-risk-banner");
  if(!banner)return;
  const verified=data && data.daily_checkpoint==="verified" && data.weekly_checkpoint==="verified" &&
    data.checkpoint_prerequisites_met===true && data.observation_status==="fresh" &&
    Number.isFinite(data.latest_observation_age_seconds) && data.latest_observation_age_seconds>=0 &&
    data.latest_observation_age_seconds<=180 && data.monitoring &&
    data.monitoring.watchdog==="healthy" && data.monitoring.equity_collector==="healthy";
  const valid=data && typeof data==="object" && (data.status!=="healthy" || verified) &&
    typeof data.status==="string" &&
    ["healthy","checkpoint_pending","checkpoint_missed",
      "evidence_stale","evidence_unavailable","monitoring_degraded"].includes(data.status);
  const status=valid?data.status:"evidence_unavailable";
  const titles={
    healthy:"Legacy main-account equity checkpoints verified",
    checkpoint_pending:"Legacy main-account checkpoint pending",
    checkpoint_missed:"Legacy main-account equity checkpoint missed",
    evidence_stale:"Legacy main-account equity evidence stale",
    evidence_unavailable:"Legacy main-account equity evidence unavailable",
    monitoring_degraded:"Legacy main-account monitoring needs attention"
  };
  const messages={
    healthy:"Daily and weekly opening checkpoints have been recorded; this does not authorize a trade.",
    checkpoint_pending:"The current UTC opening window is still available. Waiting for a signed equity observation.",
    checkpoint_missed:"A required UTC opening window closed without an authentic equity observation. Historical checkpoints cannot be backfilled.",
    evidence_stale:"Signed equity observations are no longer recent enough for the risk monitor.",
    evidence_unavailable:"The equity evidence ledger or its health endpoint could not be verified.",
    monitoring_degraded:"A collector, watchdog, clock or broker check needs attention. Checkpoints alone do not authorize a trade."
  };
  const labels={
    verified:"Verified",pending_window:"Pending opening window",
    missed_window:"Missed opening window",unavailable:"Unavailable"
  };
  const daily=valid && labels[data.daily_checkpoint]||"Unavailable";
  const weekly=valid && labels[data.weekly_checkpoint]||"Unavailable";
  const rawAge=valid?data.latest_observation_age_seconds:null;
  const age=Number.isFinite(rawAge)&&rawAge>=0?
    " · Last signed sample "+ageLabel(rawAge):" · Signed sample age unknown";
  const monitoring=valid && data.monitoring;
  const serviceLabel=value=>value==="healthy"?"Reporting":value==="stale"?"Stale":"Needs verification";
  const services=monitoring && typeof monitoring==="object"?
    " · Collector: "+serviceLabel(monitoring.equity_collector)+
    " · Watchdog: "+serviceLabel(monitoring.watchdog):" · Monitoring status unavailable";
  banner.dataset.state=status;
  text("equity-risk-title",titles[status]);
  text("equity-risk-state",status==="healthy"?"READ ONLY · VERIFIED":"RISK EVIDENCE INCOMPLETE");
  text("equity-risk-message",messages[status]);
  text("equity-risk-detail","Daily: "+daily+" · Weekly: "+weekly+age+services+
    " · FIRE requires independent authorization.");
}

async function refreshEquityCheckpointRisk() {
  try {
    const res=await fetch("/api/risk/checkpoints",{
      credentials:"same-origin",cache:"no-store",signal:AbortSignal.timeout(8000)
    });
    if(!res.ok)throw new Error("Risk health endpoint unavailable");
    const data=await res.json();
    if(!data || typeof data!=="object" ||
       data.mode!=="read_only" || data.trade_authorized!==false ||
       data.source!=="delta_demo_signed_wallet")
      throw new Error("Risk health response unverified");
    const reportAge=Date.now()-Date.parse(data.as_of);
    if(!Number.isFinite(reportAge)||reportAge < -5000||reportAge > 60000)
      throw new Error("Risk health response stale or clock inconsistent");
    renderEquityCheckpointRisk(data);
  } catch(error) {
    // Fail closed visually on network errors, malformed data and timeouts.
    renderEquityCheckpointRisk(null);
  }
}
refreshEquityCheckpointRisk();
setInterval(refreshEquityCheckpointRisk,30000);

function drawEquity(points) {
  const root = byId("equity-plot"); root.replaceChildren();
  const valid = (points || []).map(p => ({at:p.at, equity:Number(p.equity)})).filter(p => Number.isFinite(p.equity));
  if(valid.length < 2) {
    root.append(node("div","empty-chart","No equity history yet — at least two broker observations are required."));
    return;
  }
  const width = 620, height = 180, pad = 15;
  const min = Math.min(...valid.map(p=>p.equity)), max = Math.max(...valid.map(p=>p.equity));
  const range = Math.max((max - min) * 1.15, Math.max(Math.abs(max), 1) * .001);
  const bottom = min - range * .08;
  const x = i => pad + i / Math.max(1,valid.length-1)*(width-pad*2);
  const y = v => height-pad-(v-bottom)/range*(height-pad*2);
  const pts = valid.map((p,i)=>x(i).toFixed(1)+","+Math.max(5,Math.min(height-5,y(p.equity))).toFixed(1)).join(" ");
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS,"svg");svg.setAttribute("viewBox","0 0 620 180");svg.setAttribute("role","img");svg.setAttribute("aria-label","Account net equity observations, not realized profit and loss");
  const defs=document.createElementNS(svgNS,"defs"), gradient=document.createElementNS(svgNS,"linearGradient");
  gradient.setAttribute("id","equity-gradient");gradient.setAttribute("x1","0");gradient.setAttribute("x2","0");gradient.setAttribute("y1","0");gradient.setAttribute("y2","1");
  for(const [offset,opacity] of [["0%","0.25"],["100%","0"]]){const stop=document.createElementNS(svgNS,"stop");stop.setAttribute("offset",offset);stop.setAttribute("stop-color","#4ae9b2");stop.setAttribute("stop-opacity",opacity);gradient.append(stop);}
  defs.append(gradient);svg.append(defs);
  for(let i=0;i<4;i++){const line=document.createElementNS(svgNS,"line");const py=25+i*42;for(const [k,v] of Object.entries({x1:"0",y1:String(py),x2:"620",y2:String(py),stroke:"#263240","stroke-width":"1","stroke-dasharray":"4 7"}))line.setAttribute(k,v);svg.append(line);}
  const polygon=document.createElementNS(svgNS,"polygon");polygon.setAttribute("points",pad+","+(height-pad)+" "+pts+" "+(width-pad)+","+(height-pad));polygon.setAttribute("fill","url(#equity-gradient)");svg.append(polygon);
  const line=document.createElementNS(svgNS,"polyline");line.setAttribute("points",pts);line.setAttribute("fill","none");line.setAttribute("stroke","#4ae9b2");line.setAttribute("stroke-width","2.5");line.setAttribute("stroke-linecap","round");line.setAttribute("stroke-linejoin","round");svg.append(line);
  const last=valid[valid.length-1],circle=document.createElementNS(svgNS,"circle");circle.setAttribute("cx",String(x(valid.length-1)));circle.setAttribute("cy",String(Math.max(5,Math.min(height-5,y(last.equity)))));circle.setAttribute("r","4");circle.setAttribute("fill","#70ffd0");svg.append(circle);
  root.append(svg);
}

function renderDecision(events) {
  const el=byId("ai-decision");el.replaceChildren();
  const decision=(events||[]).find(e=>e.kind==="ai_decision"||e.kind==="ai_preview"||e.kind==="ai_preview_rejected");
  if(!decision){el.append(node("div","empty","No AI decision recorded yet. WAIT is valid when data or opportunities are insufficient."));return;}
  const d=decision.details||{}, header=node("div","decision-header"), name=node("div","decision-name",d.strategy||"Rejected AI response"), meta=node("span","decision-meta",timeLabel(decision.time));
  header.append(name,meta);el.append(header);
  el.append(node("p","decision-body",d.rationale||d.reason||"Decision details not available."));
  let summary = decision.kind==="ai_preview_rejected" ? "REJECTED: no accepted trading plan" :
    decision.kind==="ai_preview" ? "RESEARCH PROPOSAL — NOT EXECUTED" :
    d.mode==="demo" ? "DEMO MODE — execution must be checked separately" : "OBSERVE MODE — RESEARCH ONLY";
  if(Array.isArray(d.legs)) summary+="\nRequested BTC legs: "+d.legs.map(l=>(String(l.side||"")).toUpperCase()+" "+String(l.size||"")+" × product "+String(l.product_id||"")).join(" / ");
  el.append(node("div","decision-legs",summary));
}

function renderPositions(account) {
  const root=byId("positions-list");root.replaceChildren();
  if(account.status!=="connected") {root.append(node("div","empty","Demo account unavailable or connection not authenticated. No position state can be confirmed."));return;}
  if(!account.positions || account.positions.length===0) {root.append(node("div","empty","Exchange reports no open BTC positions at the latest successful read."));return;}
  account.positions.forEach(p=>{const row=node("div","position"),left=node("div");left.append(node("b","",p.symbol||"BTC derivative"),node("small","","Position reported by Delta DEMO"));row.append(left,node("b","",(Number(p.size)>0?"Long ":"Short ")+Math.abs(Number(p.size))+" @ "+nfmt(p.entry)));root.append(row);});
}
function eventDescription(event) {
  const d=event.details||{};
  const fields=["strategy","rationale","reason","message","error_type","product_id","side","size","contracts","count"];
  const values=fields.filter(f=>d[f]!==undefined && typeof d[f]!=="object").slice(0,3).map(f=>f.replace(/_/g," ")+": "+String(d[f]).slice(0,120));
  if(Array.isArray(d.legs))values.push(d.legs.length+" proposed leg(s)");
  return values.join(" · ") || "No additional details";
}
function renderEvents(events) {
  const root=byId("events");root.replaceChildren();
  if(!events?.length){root.append(node("div","empty","No bot activity recorded yet. Start observe mode to populate this timeline."));return;}
  events.slice(0,30).forEach(e=>{
    const row=node("div","event"),first=node("div","event-name"),dot=node("span","event-chip"),kind=e.kind||"event";
    if(/alert|failure|error|critical|halt/i.test(kind))dot.classList.add("error");else if(/reject|pending|warn/i.test(kind))dot.classList.add("warning");
    first.append(dot,document.createTextNode(kind.replace(/_/g," ")));
    row.append(first,node("div","event-description",eventDescription(e)),node("div","event-time",timeLabel(e.time)));root.append(row);
  });
}
function render(data) {
  if (data.live && Date.now()-Date.parse(data.live.checked_at)>90000) {
    data.live.market = {status:"stale"};
    data.live.account = {status:"unavailable"};
  }
  latest = data;
  renderDesk(data);
  const runner=data.runner||{}, live=data.live||{}, market=live.market||{}, account=live.account||{}, ledger=data.ledger||{};
  text("refresh-label","Updated "+new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit"}));
  // The top runtime pill belongs to the signed isolated-account report.
  // This legacy runner heartbeat must never override BTC/Gold worker status.
  text("agent-action",runner.action||"No heartbeat");
  text("last-heartbeat",runner.age_seconds==null?"No runner heartbeat recorded":ageLabel(runner.age_seconds));
  text("mode-label",runner.mode==="demo"?"DEMO TRADING MODE":runner.mode==="observe"?"READ-ONLY OBSERVER":"NOT VERIFIED");
  text("agent-schedule",runner.schedule==="crypto-24x7"?"24/7 CRYPTO":runner.schedule==="nyse-cash-observe"?"NYSE CASH HOURS · DEEPSEEK":runner.schedule==="nyse"?"NYSE HOURS":"—");
  text("btc-bid",market.status==="fresh"?"$"+nfmt(market.bid):"—");
  text("btc-ask",market.status==="fresh"?"$"+nfmt(market.ask):"—");
  text("quote-status",market.status==="fresh"?"Delta testnet · quote "+ageLabel(market.age_seconds):market.status==="waiting"?"Connecting to exchange":"Price unavailable / stale");
  const spread=market.status==="fresh"?Number(market.ask)-Number(market.bid):NaN;
  text("btc-spread",Number.isFinite(spread)?"Spread $"+nfmt(spread):"No reliable spread");
  text("confirmed-fills",ledger.confirmed_btc_fills??0);
  text("open-orders",account.status==="connected"?account.account_open_orders:"—");
  text("account-status",account.status==="connected"?"Authenticated demo account":"Account read unavailable");
  text("broker-access",account.status==="connected"?"Connected · read only":"Not verified");
  text("positions-count",account.status==="connected"?account.btc_open_positions:"—");
  text("net-equity",account.status==="connected"&&account.net_equity!=null?nfmt(account.net_equity):"—");
  text("equity-label","Demo net equity (currency per broker)");
  const pts=ledger.equity_points||[];
  text("point-count",pts.length+" observations");
  drawEquity(pts);
  renderDecision(data.events||[]);
  renderPositions(account);
  renderEvents(data.events||[]);
  byId("halt-banner").hidden=!data.halted;
}
async function update() {
  try {
    const res=await fetch("/api/overview",{credentials:"same-origin",cache:"no-store",signal:AbortSignal.timeout(12000)});
    if(!res.ok)throw new Error("API unavailable");
    render(await res.json());
  } catch(err) {
    latest = null;
    priorPrice="";text("mid","—");text("top-quote","Fresh quote unavailable");
    showPriority("Connection lost · showing the last received records.");
    text("sample-info","Offline · historical chart");
    text("refresh-label","Dashboard offline");
    // Losing the legacy main-account observer must not mark active BTC/Gold
    // isolated workers offline. The isolated report owns the top status.
  } finally { setTimeout(update,10000); }
}
document.querySelectorAll(".nav").forEach(link=>link.addEventListener("click",()=>{
  document.querySelectorAll(".nav").forEach(x=>x.classList.remove("active"));link.classList.add("active");
}));

let latest = null;
function answer(question) {
  if (selectedRecord && /here|selected|compare|this|fill|why/i.test(question)) return describe(selectedRecord);
  if (/previous|last trade|completed trade|recent fill/i.test(question)) {
    const fills = chartRecords.filter(r=>r.type==="fill");
    if(!fills.length)return "No confirmed fills in the displayed records.";
    return fills.slice(0,3).map(describe).join("\n");
  }
  if (/fee|funding|performance|net result/i.test(question)) {
    const v=latest?.live?.performance;
    if(!v)return "No current signed wallet postings available.";
    return "Account-wide 24h wallet postings through "+timeLabel(v.at)+": "+(Object.entries(v.assets).map(([asset,p])=>asset+" net "+p.net+" (signed fees "+p.fees+", funding "+p.funding+")").join("; ")||"no matching postings.");
  }
  if (!latest) return "Dashboard disconnected. Please try again after it reconnects.";
  const live = latest.live || {};
  if (/decision|why|wait|strategy|analysis/i.test(question)) {
    const event = latest.events?.find(e => ["ai_decision","ai_preview","ai_preview_rejected"].includes(e.kind));
    if (!event) return "No decision has been recorded yet.";
    return [event.details?.strategy || "Decision record", event.details?.rationale || event.details?.reason, timeLabel(event.time)].filter(Boolean).join(" · ");
  }
  if (!(Date.now() - Date.parse(live.checked_at) < 90000)) return "Waiting for a current exchange snapshot.";
  if (/position|order/i.test(question)) {
    const a = live.account;
    return a?.status === "connected" ? a.btc_open_positions + " open BTC positions and " + a.account_open_orders + " open account orders at the last exchange check." : "Account data is unavailable.";
  }
  if (/price|quote|spread|bid|ask|midpoint/i.test(question)) {
    const m = live.market;
    return m?.status === "fresh" ? "Delta demo bid $" + nfmt(m.bid) + ", ask $" + nfmt(m.ask) + ", spread $" + nfmt(Number(m.ask) - Number(m.bid)) + "." : "Waiting for a fresh BTC quote.";
  }
  return "I can look up BTC prices, spreads, open positions, open orders and the latest recorded decision.";
}

function ask(question) {
  if (!question.trim()) return;
  const log = byId("messages");
  log.append(node("p","asker",question),node("p","reply",answer(question)));
  while (log.children.length > 40) log.firstElementChild.remove();
  log.scrollTop = log.scrollHeight;
}
byId("chat-form").addEventListener("submit", event => {
  event.preventDefault();
  ask(byId("question").value);
  byId("question").value = "";
});
byId("prompts").addEventListener("click", event => {
  if (event.target.tagName === "BUTTON") ask(event.target.textContent);
});


let historyBars = [], chartRecords = [], markers = [], frozenBars = null, selectedRecord = null;
let decisionMarkerKey;
let barCount = 12, selectedTime = null, priorPrice = "", chatTrigger = null;
const chart = byId("trace");
const formatTime = t => new Date(t).toISOString().slice(11,16);
const decisionKinds = new Set(["ai_decision","ai_preview","ai_preview_rejected"]);
function makeRecords(data) {
  const events = (data.events || []).map(e => ({type:"event", key:e.kind + e.time + JSON.stringify(e.details), at:Date.parse(decisionKinds.has(e.kind) ? e.details.at || e.time : e.time), ...e}));
  const orders = new Map(events.filter(e => e.details.order_id && /^(entry|exit)_submitted$/.test(e.kind)).map(e=>[String(e.details.order_id),e]));
  const decisions = new Map(events.filter(e=>decisionKinds.has(e.kind) && e.details.decision_id).map(e=>[e.details.decision_id,e]));
  const unique = new Map();
  for (const fill of [...(data.live?.recent_fills || []), ...(data.ledger?.fills || [])]) unique.set(String(fill.id),fill);
  const fills = [...unique.values()].map(fill => {
    const order = orders.get(fill.order_id);
    const decision = order && decisions.get(order.details.decision_id);
    const leg = decision?.details.legs?.find(l=>l.product_id===order.details.product_id && l.side===fill.side);
    return {type:"fill",key:"fill-"+fill.id,at:fill.time_ms,kind:order?.kind==="entry_submitted"?"entry_fill":order?.kind==="exit_submitted"?"exit_fill":"confirmed_fill",
      fill, reference:order?.kind==="entry_submitted"?leg?.reference_price:null,decision};
  });
  return [...events,...fills].filter(r=>Number.isFinite(r.at)).sort((a,b)=>b.at-a.at);
}
function describe(r) {
  const when = timeLabel(new Date(r.at).toISOString());
  if (r.type==="candle") {
    const b=r.bar;
    return when+" · Delta BTCUSD 5m OHLC · Open "+nfmt(b.open)+" · High "+nfmt(b.high)+" · Low "+nfmt(b.low)+" · Close "+nfmt(b.close);
  }
  if (r.type==="fill") {
    const f=r.fill;
    const comparison = r.reference!=null ? "Decision quote "+nfmt(r.reference)+" · fill minus quote "+nfmt(Number(f.price)-Number(r.reference)) : "No linked proposal price recorded.";
    return when+" · Confirmed Delta fill · "+f.side+" "+f.size+" "+f.symbol+" at "+nfmt(f.price)+" · fee "+f.fee+" "+f.asset+". "+comparison;
  }
  const d=r.details;
  return when+" · Bot journal · "+(d.strategy||r.kind.replace(/_/g," "))+" · "+(d.rationale||d.reason||eventDescription(r))+(d.spread!=null?" · Recorded BTC spread $"+nfmt(d.spread):"");
}
function visibleBars(){return frozenBars || historyBars.slice(-barCount);}
async function openReplay(r) {
  inspect(r);
  byId("inspection").scrollIntoView({block:"center"});
  if (visibleBars().some(b=>b.time === Math.floor(r.at/300000)*300)) return;
  frozenBars=[];
  drawChart();
  text("sample-info","Loading candles at selected time…");
  try {
    const response=await fetch("/api/candles?at="+Math.floor(r.at/1000),{signal:AbortSignal.timeout(12000)});
    if(!response.ok) throw Error();
    const bars=await response.json();
    if(selectedRecord!==r) return;
    frozenBars=bars;
    text("sample-info","Historical candles · tap Live to resume");
  } catch {
    if(selectedRecord!==r) return;
    text("sample-info","Historical candles unavailable for this event");
  }
  drawChart();
}
function inspect(r) {
  frozenBars ||= visibleBars().slice();
  selectedRecord=r;selectedTime=r.at;
  text("sample-info","Inspection paused · tap Live to resume");
  text("inspect-title",r.type==="candle"?"Candle inspection":r.kind.replace(/_/g," "));
  text("inspect-text",describe(r));byId("inspection").hidden=false;
  const sequenceId=r.details?.decision_id || r.decision?.details.decision_id;
  const stages=sequenceId ? chartRecords.filter(e=>(e.details?.decision_id || e.decision?.details.decision_id)===sequenceId).slice().reverse() : [];
  byId("sequence").replaceChildren(...stages.map(e=>node("li","",formatTime(e.at)+" UTC · "+e.kind.replace(/_/g," "))));
  text("context-chat",r.type==="fill"?"Compare this fill":r.type==="candle"?"Ask about this candle":"Explain this event");
  drawChart();
}
function resumeLive(){
  frozenBars=null;selectedRecord=null;selectedTime=null;byId("inspection").hidden=true;drawChart();
}
function drawChart() {
  const bars=visibleBars(), w=chart.clientWidth,h=chart.clientHeight,dpr=window.devicePixelRatio||1;
  chart.width=Math.round(w*dpr);chart.height=Math.round(h*dpr);markers=[];
  if (!w || !h) return;
  const ctx=chart.getContext("2d");ctx.scale(dpr,dpr);
  if (!bars.length){ctx.fillStyle="#aaa";ctx.fillText("Waiting for BTCUSD candle history",12,h/2);return;}
  const lo=Math.min(...bars.map(b=>+b.low)),hi=Math.max(...bars.map(b=>+b.high)),range=Math.max(hi-lo,0.01);
  const first=bars[0].time,last=bars.at(-1).time,step=(w-68)/((last-first)/300+1);
  const x=t=>5+(0.5+(t-first)/300)*step;
  const y=p=>28+(hi-p)/range*(h-66);
  ctx.font="10px monospace";
  for(let i=0;i<=3;i++){
    const price=hi-range*i/3,cy=y(price);ctx.strokeStyle="#383b40";ctx.beginPath();ctx.moveTo(0,cy);ctx.lineTo(w-57,cy);ctx.stroke();ctx.fillStyle="#b9bec4";ctx.fillText(nfmt(price,0),w-52,cy+3);
  }
  for(const b of bars){
    const cx=x(b.time),up=+b.close>=+b.open;ctx.strokeStyle=ctx.fillStyle=up?"#66d8bb":"#ef908e";
    ctx.beginPath();ctx.moveTo(cx,y(+b.high));ctx.lineTo(cx,y(+b.low));ctx.stroke();
    ctx.fillRect(cx-step*.26,Math.min(y(+b.open),y(+b.close)),Math.max(1,step*.52),Math.max(1,Math.abs(y(+b.open)-y(+b.close))));
  }
  const layers=new Map();
  for(const r of chartRecords){
    if(!decisionKinds.has(r.kind)&&r.type!=="fill")continue;
    const sec=Math.floor(r.at/300000)*300;
    if(sec<first||sec>last)continue;
    const level=layers.get(sec)||0;layers.set(sec,level+1);
    const cx=x(sec),cy=10+(level%4)*13;
    const glyph=r.kind==="entry_fill"?"▲":r.kind==="exit_fill"?"■":r.type==="fill"?"●":"◇";
    ctx.fillStyle=r.type==="fill"?"#89c8ff":"#f5be61";ctx.font="bold 14px sans-serif";ctx.fillText(glyph,cx-5,cy+5);markers.push({cx,cy,r});
  }
  if(selectedTime!==null){
    const cx=x(Math.floor(selectedTime/300000)*300);
    if(cx>=0 && cx<w-55){ctx.strokeStyle="#efc581";ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(cx,22);ctx.lineTo(cx,h-20);ctx.stroke();ctx.setLineDash([]);}
  }
  ctx.font="10px monospace";ctx.fillStyle="#b9bec4";ctx.fillText(formatTime(first*1000),3,h-4);ctx.fillText(formatTime(last*1000),w-99,h-4);
}
function pick(event){
  const bars=visibleBars();if(!bars.length)return;
  const rect=chart.getBoundingClientRect(),px=event.clientX-rect.left,py=event.clientY-rect.top;
  const hit=markers.find(m=>Math.hypot(m.cx-px,m.cy-py)<12);
  if(hit){inspect(hit.r);return;}
  const first=bars[0].time,last=bars.at(-1).time;
  const target=first+((px-5)/(rect.width-68)*((last-first)+300)-150);
  const bar=bars.reduce((a,b)=>Math.abs(a.time-target)<Math.abs(b.time-target)?a:b);
  inspect({type:"candle",at:bar.time*1000,bar});
}
chart.addEventListener("pointerdown",e=>{chart.setPointerCapture(e.pointerId);pick(e);});
chart.addEventListener("pointermove",e=>{if(chart.hasPointerCapture(e.pointerId))pick(e);});
chart.addEventListener("keydown",e=>{
  if(!["ArrowRight","ArrowLeft"].includes(e.key))return;
  const bars=visibleBars();if(!bars.length)return;e.preventDefault();
  const idx=selectedTime==null?bars.length-1:bars.findIndex(b=>b.time===Math.floor(selectedTime/300000)*300);
  const bar=bars[Math.max(0,Math.min(bars.length-1,idx+(e.key==="ArrowRight"?1:-1)))];
  inspect({type:"candle",at:bar.time*1000,bar});
});
byId("ranges").addEventListener("click",e=>{
  if(!e.target.dataset.bars)return;barCount=+e.target.dataset.bars;
  for(const button of byId("ranges").children)button.setAttribute("aria-pressed",String(button===e.target));
  resumeLive();
});
byId("go-live").onclick=resumeLive;
new ResizeObserver(drawChart).observe(chart.parentElement);
function openChat(trigger){
  chatTrigger=trigger;byId("chat").classList.add("open");byId("question").focus();
}
function closeChat(){byId("chat").classList.remove("open");chatTrigger?.focus();}
byId("open-chat").onclick=e=>openChat(e.currentTarget);
byId("chat-close").onclick=closeChat;
byId("context-chat").onclick=e=>{openChat(e.currentTarget);ask("Explain this selection");};
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&byId("chat").classList.contains("open"))closeChat();});
function showPriority(message,link){
  const el=byId("priority");el.hidden=!message;el.textContent=message||"";
  if(message && link){const a=node("a",""," View exchange details");a.href="#position-card";el.append(a);}
}
function renderDesk(data){
  const live=data.live||{},market=live.market||{},account=live.account||{},runner=data.runner||{};
  text("heartbeat-head","Heartbeat "+ageLabel(runner.age_seconds));
  const fresh=market.status==="fresh" && Date.now()-Date.parse(live.checked_at)<90000;
  const price=fresh?"$"+nfmt((+market.bid + +market.ask)/2):"—";
  if(price!==priorPrice){
    byId("mid").replaceChildren(...Array.from(price,(c,i)=>node("span",priorPrice && c!==priorPrice[i]?"digit-tick":"",c)));
    priorPrice=price;
  }
  historyBars=live.candles||[];
  if (fresh && byId("top-quote").textContent !== "Bid $"+nfmt(market.bid)+"  /  Ask $"+nfmt(market.ask))
    text("top-quote","Bid $"+nfmt(market.bid)+"  /  Ask $"+nfmt(market.ask));
  if (!fresh) text("top-quote","No fresh bid or ask");
  chartRecords=makeRecords(data);drawChart();
  if (!frozenBars) text("sample-info",historyBars.length?"Last candle "+formatTime(historyBars.at(-1).time*1000)+" UTC":"Exchange history unavailable");
  const alert=chartRecords.find(r=>["closeout_alert","shutdown_exposure_alert","btc_flat_verified"].includes(r.kind));
  showPriority(data.halted?"Execution halted · review exchange exposure.":alert && alert.kind!=="btc_flat_verified"?"Closeout requires verification.":runner.status==="stale"?"Observer heartbeat stale.":!fresh?"Market data delayed · last check "+timeLabel(live.checked_at):account.status!=="connected"?"Exchange account unavailable.":null,true);
  const pos=byId("position-card");pos.classList.toggle("exposed",account.btc_open_positions>0);
  text("next-scan",runner.schedule==="nyse-cash-observe"&&runner.action==="nyse_cash_closed_no_ai"?
    "DeepSeek paused · NYSE cash market closed (opens 9:30 AM New York time on trading days)":
    "Next eligible scan · "+(runner.status==="running"&&runner.next_scan?
      timeLabel(runner.next_scan):"Awaiting runner schedule"));
  text("exit-due",account.btc_open_positions>0?"Timed exit · "+(runner.exit_due?timeLabel(runner.exit_due):"No deadline recorded"):"");
  const latestDecision=chartRecords.find(r=>decisionKinds.has(r.kind));
  if (latestDecision && decisionMarkerKey && latestDecision.key!==decisionMarkerKey && !frozenBars &&
      !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    chart.animate([{opacity:.65},{opacity:1}],{duration:350});
  }
  decisionMarkerKey=latestDecision?.key;
  const replay=chartRecords.filter(r=>r.type==="fill"||decisionKinds.has(r.kind)||/entry_|exit_|partial_fill|flat_verified|closeout|exposure|halt|rejection/.test(r.kind));
  const root=byId("replay"), signature=replay.map(r=>r.key).join("|");
  if(root.dataset.signature!==signature){
    root.dataset.signature=signature;root.replaceChildren();
    for(const r of replay){const b=node("button","replay-item",timeLabel(new Date(r.at).toISOString())+"  ·  "+(r.details?.strategy||r.kind.replace(/_/g," ")));b.onclick=()=>openReplay(r);root.append(b);}
    if(!replay.length)root.append(node("p","","No execution or decision records yet."));
  }
  const perf=live.performance,ret=byId("returns");ret.replaceChildren();
  if(!perf){ret.textContent="Wallet postings unavailable.";return;}
  for(const [asset,v] of Object.entries(perf.assets)){
    ret.append(node("h3","",asset+"  "+v.net),node("p","","Cash flow & settlement "+v.cashflow+" · Signed fees and rebates "+v.fees+" · Funding "+v.funding));
  }
  if(!Object.keys(perf.assets).length)ret.append(node("p","","No matching wallet postings in this window."));
  ret.append(node("small","","Exchange wallet · account-wide · through "+timeLabel(perf.at)));
}
byId("dismiss-record").onclick=resumeLive;
update();

const fireMarket = byId("fire-market");
const marketPath = (base, symbol) => symbol === "XAUTUSD" ? base + "/XAUTUSD" : base;
let fireRevision = 0;
let postingFire = false;
let fireTradingEnabled = false;
function renderFireExecution(data) {
  const button=byId("fire-preview"), container=byId("fire-results"), status=byId("fire-status");
  if(!button || !container || !status)return;
  fireTradingEnabled=true;
  text("fire-mode-label","DELTA INDIA DEMO · ORDER EXECUTION");
  text("fire-description","One tap asks GPT-6 to decide "+fireMarket.value+" direction, contract size, stop-loss and take-profit. The demo broker must verify an entry fill and BOTH protective orders. Kimi cannot trade.");
  text("fire-disclosure","REAL DELTA DEMO ORDERS — no real funds. One paid GPT-6 completion per press. Uncertain exchange outcomes block additional FIRE requests. Margin budget per market: 20% of demo equity.");
  const stages={
    idle:"Ready for a manual GPT-6 Demo trade.",
    requested:"FIRE accepted. Starting GPT-6…",
    reasoning:"GPT-6 is deciding the trade…",
    preflight:"Checking fresh "+fireMarket.value+" quote, account orders, and margin eligibility…",
    submitting:"Submitting the "+fireMarket.value+" market entry with attached SL/TP…",
    reconciling:"Checking the entry against Delta Demo. Never resubmitting on timeout…",
    verifying_protection:"Checking the fill and BOTH broker protective orders…",
    protected_active:"Entry filled; STOP-LOSS and TAKE-PROFIT are verified on Delta Demo.",
    flat_verified:"Position closed. FIRE is ready for the next demo trade.",
    rejected_no_order:"No valid trade was submitted. Review GPT-6 response and demo account.",
    exposure_unknown:"ALERT: Exposure/protection uncertain! Check Delta Demo account immediately.",
    aborted_flat:"Previous FIRE was abandoned before submission; exchange flat.",
    cancelled_flat_verified:"Entry cancelled and demo account flat."
  };
  button.disabled=!["idle","flat_verified","rejected_no_order","aborted_flat","cancelled_flat_verified"].includes(data.status);
  button.textContent=button.disabled?"FIRE · "+(data.status||"processing").replaceAll("_"," ").toUpperCase():"FIRE · "+fireMarket.value+" · EXECUTE DEMO";
  const active=data.status==="protected_active";
  status.textContent=stages[data.status]||"Unknown FIRE execution state; inspect account before pressing again.";
  if(data.status==="rejected_no_order" && data.reason_code)
    status.textContent+=" · "+String(data.reason_code).replaceAll("_"," ");
  container.replaceChildren();
  if(data.indicators){
    const i=data.indicators, tile=node("div","fire-result");
    tile.append(node("div","fire-result-title","Market at last Fire · "+data.symbol+" · "+
      new Date(i.as_of*1000).toLocaleTimeString()));
    const grid=node("div","fire-points");
    for(const [label,t] of [["15m EMA20",i.ema_15m],["1h EMA20",i.ema_1h]]){
      const item=node("div","fire-point");
      const side=t && (t.close>t.ema20?"Above":t.close<t.ema20?"Below":"At");
      item.append(node("small","",label),node("b","",t?side+" · "+t.slope:"Unavailable"));
      grid.append(item);
    }
    tile.append(grid,node("p","fire-proof","UTC session VWAP "+(i.session_vwap??"—")+
      " · 5m ATR(14) "+(i.atr_5m??"—")));
    const e=i.since_exit;
    tile.append(node("p","fire-proof",e?"Since exit at "+e.price+" · "+Math.floor(e.seconds/60)+
      "m · price change "+e.move+" ("+(e.move_atr??"—")+" ATR)":"Previous verified exit unavailable"));
    if(e && e.broke_pre_exit_high!=null){
      const breaks=[e.broke_pre_exit_high && "high",e.broke_pre_exit_low && "low"].filter(Boolean);
      tile.append(node("p","fire-proof","Since exit · prior 5m range broken: "+(breaks.join(" and ")||"neither side")));
    }
    container.append(tile);
  }
  if(data.budget){
    const b=data.budget;
    container.append(node("p","fire-proof","Budget at last check: $"+Number(b.margin_budget_usd).toFixed(2)+
      " · "+Number(b.leverage)+"× · up to "+b.max_contracts_per_entry+" contracts"));
  }
  if(data.direction){
    const tile=node("div","fire-result");
    tile.append(node("div","fire-result-title","GPT-6 · "+fireMarket.value+" · DELTA DEMO"));
    tile.append(node("strong","fire-direction",data.direction+" · "+data.contracts+" contract(s)"));
    const grid=node("div","fire-points");
    for(const [label,value] of [["STOP LOSS",data.stop_loss],["TAKE PROFIT",data.take_profit]]){
      const metric=node("div","fire-point");
      metric.append(node("small","",label),node("b","",value==null?"—":value));
      grid.append(metric);
    }
    tile.append(grid);
    if(data.sizing_estimate){
      const estimate=data.sizing_estimate;
      tile.append(node("p","fire-proof","At submission · estimated exposure $"+Number(estimate.notional_usd).toFixed(2)+
        " · estimated loss at stop $"+Number(estimate.loss_at_stop_usd).toFixed(2)+" before fees and slippage"));
    }
    tile.append(node("p","fire-proof",
      active?"BROKER CONFIRMED: entry and two protective orders.":
      data.status==="flat_verified"?"EXCHANGE FLAT: no live position or orders.":
      "Broker protection NOT YET verified. This is not a confirmed protected position."));
    container.append(tile);
  }
  if(data.status==="exposure_unknown") {
    container.append(node("p","fire-error",
      "Manual broker verification required. Do not fire again until selected-market demo positions and pending orders are reconciled."));
  }
}

function renderFire(data) {
  const button=byId("fire-preview"), container=byId("fire-results"), status=byId("fire-status");
  if(!button || !container || !status)return;
  const remaining=Number(data.cooldown_seconds||0);
  button.disabled=data.status==="running"||remaining>0;
  button.textContent=data.status==="running"?"Analyzing GPT-6…":
    remaining>0?"FIRE · Retry in "+Math.ceil(remaining/60)+"m":"FIRE · "+fireMarket.value+" · Analyze only";
  const messages={
    idle:"Ready. Pressing FIRE requests GPT-6 analysis; it never submits an order.",
    running:"Contacting GPT-6. One paid request may be in progress.",
    completed:"GPT-6 analysis completed. No orders submitted.",
    failed:"No validated GPT-6 analysis was completed. No orders submitted."
  };
  status.textContent=messages[data.status]||"Comparison unavailable.";
  if(!data.result || !data.result.results)return;
  container.replaceChildren();
  for(const [role,title] of [["fire","GPT-6 · FIRE"]]) {
    const value=data.result.results[role]||{}, tile=node("div","fire-result");
    tile.append(node("div","fire-result-title",title));
    if(value.decision) {
      const p=value.decision;
      tile.append(node("strong","fire-direction",String(p.direction||"")+
        " · "+String(p.contracts||"")+" contract(s)"));
      const grid=node("div","fire-points");
      for(const [label,number] of [["STOP LOSS",p.stop_loss],["TAKE PROFIT",p.take_profit]]) {
        const metric=node("div","fire-point");
        metric.append(node("small","",label),node("b","",number));
        grid.append(metric);
      }
      tile.append(grid);
    } else {
      tile.append(node("p","fire-error","No validated trading decision returned."));
    }
    tile.append(node("small","fire-time",
      typeof value.latency_ms==="number"?"Model latency: "+value.latency_ms+"ms":"Research only · Not executed"));
    container.append(tile);
  }
  const footer=node("p","fire-proof","Snapshot: "+String(data.result.snapshot_at||"unknown")+
    " · GPT-6 research only. This is not an execution.");
  container.append(footer);
}
async function refreshFire() {
  const button=byId("fire-preview");
  if(!button || postingFire)return;
  const revision = ++fireRevision, symbol = fireMarket.value;
  try {
    const modeResponse=await fetch(marketPath("/api/fire",symbol),{credentials:"same-origin",cache:"no-store"});
    if(!modeResponse.ok)throw new Error("FIRE mode unavailable");
    const mode=await modeResponse.json();
    if(revision !== fireRevision)return;
    if(mode.execution_enabled===true){
      renderFireExecution(mode);
      return;
    }
    fireTradingEnabled=false;
    text("fire-mode-label","READ-ONLY PROBE");
    text("fire-disclosure","Read-only research. One paid GPT-6 completion may be made. No demo orders are submitted.");
    const response=await fetch(marketPath("/api/fire-preview",symbol),{credentials:"same-origin",cache:"no-store"});
    if(!response.ok)throw new Error("Fire status unavailable");
    const result=await response.json();
    if(revision === fireRevision)renderFire(result);
  } catch(err) {
    if(revision !== fireRevision)return;
    text("fire-status","GPT-6 analysis unavailable. No trading order can be placed from this panel.");
    button.disabled=true;
  }
}
const fireButton=byId("fire-preview");
if(fireButton)fireButton.addEventListener("click",async()=>{
  if(fireButton.disabled || postingFire)return;
  if(!fireTradingEnabled &&
      !window.confirm("Run a read-only GPT-6 analysis? This may use one paid Top Billing completion. It will NOT place orders."))return;
  ++fireRevision;
  postingFire=true;
  fireMarket.disabled=true;
  fireButton.disabled=true;
  text("fire-status",fireTradingEnabled?
    "Executing one GPT-6 Delta DEMO trade request…":"Requesting a read-only GPT-6 analysis…");
  try {
    const path=fireTradingEnabled?"/api/fire":"/api/fire-preview";
    const response=await fetch(marketPath(path,fireMarket.value),{
      method:"POST", credentials:"same-origin",cache:"no-store",
      headers:{"X-Tradebot-Action":fireTradingEnabled?"fire-execute":"fire-preview"}
    });
    const payload=await response.json();
    if(fireTradingEnabled)renderFireExecution(payload);
    else renderFire(payload);
    if(!response.ok)
      text("fire-status",fireTradingEnabled?
        "FIRE blocked: another trade, unresolved broker state, or cooldown. No NEW request was accepted.":
        "Preview blocked or in cooldown. No orders placed.");
  } catch(err) {
    text("fire-status",fireTradingEnabled?
      "FIRE request status uncertain. Check Delta Demo positions and refresh; do not press again.":
      "Unable to start GPT-6 preview. No orders placed.");
    fireButton.disabled=true;
  } finally {
    postingFire=false;
    fireMarket.disabled=false;
  }
});
fireMarket.addEventListener("change", () => {
  fireButton.disabled = true;
  byId("fire-results").replaceChildren();
  text("fire-status", "Loading " + fireMarket.value + "…");
  refreshFire();
});
refreshFire();setInterval(refreshFire,6000);


async function refreshLearning() {
  const container=byId("learning-hypotheses");
  if(!container)return;
  try {
    const response=await fetch("/api/learning", {credentials:"same-origin",cache:"no-store"});
    if(!response.ok)throw new Error("Research status unavailable");
    const data=await response.json();
    text("learning-events",data.evidence_events);
    text("learning-candidates",data.candidate_lessons);
    text("learning-validated",data.validated_lessons);
    text("learning-fills",data.unattributed_broker_fills||0);
    const freshness=data.last_observation_at ? " · Last broker observation "+timeLabel(data.last_observation_at):"";
    const watcherStatus=data.watcher_status||"not_running";
    const monitoring=watcherStatus==="not_running"||watcherStatus==="stale"?
      "Watcher "+watcherStatus.replace("_"," ")+"; no active Kimi monitoring confirmed.":
      data.kimi_paid_enabled===true?
      "Watcher active · paid Kimi reviews enabled when a position is observed.":
      "Watcher active · recording only; paid Kimi reviews disabled.";
    text("learning-status",(data.status==="available"?
      (data.active_position?"demo position observed. ":"No active demo position observed. "):
      "Learning database not initialized. ")+monitoring+freshness);
    container.replaceChildren();
    if(!Array.isArray(data.recent_hypotheses)||!data.recent_hypotheses.length) {
      container.append(node("p","empty","No Kimi hypotheses yet. Research starts after a demo position is observed."));
    } else {
      for(const item of data.recent_hypotheses.slice(0,3)) {
        const entry=node("article","learning-hypothesis");
        entry.append(
          node("div","learning-tag","UNVERIFIED · KIMI HYPOTHESIS"),
          node("strong","",item.hypothesis||"Hypothesis unavailable"),
          node("p","","Counterevidence: "+(item.counterevidence||"Not supplied")),
          node("p","","Applies when: "+(item.applicable_when||"Not supplied"))
        );
        container.append(entry);
      }
    }
  } catch(error) {
    text("learning-status","Learning status unavailable. GPT-6 remains independent.");
  }
}
refreshLearning();setInterval(refreshLearning,20000);
