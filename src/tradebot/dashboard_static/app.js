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
  text("runtime-status",runner.status==="running" ? "RUNNING · "+(runner.mode==="demo"?"DEMO TRADING":"OBSERVING") : runner.status==="stale" ? "HEARTBEAT STALE" : runner.status==="stopped"?"STOPPED":"NO RUNNING BOT VERIFIED");
  byId("runtime-pill").dataset.state=runner.status||"unknown";
  text("agent-action",runner.action||"No heartbeat");
  text("last-heartbeat",runner.age_seconds==null?"No runner heartbeat recorded":ageLabel(runner.age_seconds));
  text("mode-label",runner.mode==="demo"?"DEMO TRADING MODE":runner.mode==="observe"?"READ-ONLY OBSERVER":"NOT VERIFIED");
  text("agent-schedule",runner.schedule==="crypto-24x7"?"24/7 CRYPTO":runner.schedule==="nyse"?"NYSE HOURS":"—");
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
    text("runtime-status","DATA CONNECTION LOST");
    byId("runtime-pill").dataset.state="stale";
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
  text("next-scan","Next eligible scan · "+(runner.status==="running"&&runner.next_scan?timeLabel(runner.next_scan):"Awaiting runner schedule"));
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
