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
  account.positions.forEach(p=>{const row=node("div","position"),left=node("div");left.append(node("b","",p.symbol||"BTC derivative"),node("small","","Position reported by Delta DEMO"));row.append(left,node("b","",p.size+" contracts"));root.append(row);});
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
  latest = data;
  updateTape(data.live);
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
    const res=await fetch("/api/overview",{credentials:"same-origin",cache:"no-store"});
    if(!res.ok)throw new Error("API unavailable");
    render(await res.json());
  } catch(err) {
    latest = null;
    updateTape(null);
    text("refresh-label","Dashboard offline");
    text("runtime-status","DATA CONNECTION LOST");
    byId("runtime-pill").dataset.state="stale";
  }
}
document.querySelectorAll(".nav").forEach(link=>link.addEventListener("click",()=>{
  document.querySelectorAll(".nav").forEach(x=>x.classList.remove("active"));link.classList.add("active");
}));

let latest = null;
const samples = [];

function paintTrace() {
  const canvas = byId("trace");
  const width = canvas.clientWidth, height = canvas.clientHeight;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  if (!samples.length || !width || !height) return;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const prices = samples.map(s => s.price);
  const low = Math.min(...prices), high = Math.max(...prices);
  const first = samples[0], last = samples[samples.length - 1];
  const duration = Math.max(1, last.at - first.at);
  ctx.strokeStyle = ctx.fillStyle = "#71efcc";
  ctx.lineWidth = 2;
  ctx.beginPath();
  let previous, x, y;
  for (const sample of samples) {
    x = 5 + (width - 10) * (sample.at - first.at) / duration;
    y = high === low ? height / 2 : 8 + (height - 16) * (high - sample.price) / (high - low);
    if (!previous || sample.at - previous.at > 90000) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
    previous = sample;
  }
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(x, y, 4, 0, 2 * Math.PI);
  ctx.fill();
}

function updateTape(live) {
  const market = live?.market;
  const at = Date.parse(live?.checked_at);
  const age = Date.now() - at;
  const price = (Number(market?.bid) + Number(market?.ask)) / 2;
  if (market?.status !== "fresh" || !(age < 90000) || !Number.isFinite(price)) {
    text("mid", "—");
    text("sample-info", "Waiting for a fresh BTC quote");
    return;
  }
  text("mid", "$" + nfmt(price));
  if (samples.length && at <= samples[samples.length - 1].at) return;
  samples.push({at, price});
  if (samples.length > 180) samples.shift();
  paintTrace();
  text("sample-info", samples.length + " observations · " + new Date(at).toLocaleTimeString());
  byId("mid").classList.remove("new-price");
  void byId("mid").offsetWidth;
  byId("mid").classList.add("new-price");
}

function answer(question) {
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
new ResizeObserver(paintTrace).observe(byId("trace").parentElement);
update();setInterval(update,10000);
