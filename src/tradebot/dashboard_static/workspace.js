"use strict";
/* Trading Bot 2.0 mobile-first workspace — PRESENTATION ONLY.
 * Uses existing broker-signed, cached GET endpoints. No POST, orders or models.
 * Never derives a false "all protected" signal from order counts.
 */
(() => {
  const $ = id => document.getElementById(id);
  const shell = document.querySelector(".content");
  if (!shell || !$("home-summary")) return;

  const known = new Set(["home", "bots", "analytics", "activity", "desk"]);
  const sections = new Map();
  for (const child of Array.from(shell.children)) {
    if (child.classList.contains("dock") || child.classList.contains("footer")) continue;
    const id = child.id;
    const view = id === "overview" || id === "home-summary" ? "home"
      : id === "isolated-accounts" ? "bots"
      : id === "autonomous-performance" ? "analytics"
      : id === "activity" ? "activity" : "desk";
    child.dataset.workspaceSection = view;
    if (!sections.has(view)) sections.set(view, []);
    sections.get(view).push(child);
  }
  const translate = {
    "overview":"home", "isolated-accounts":"bots",
    "autonomous-performance":"analytics", "trades":"desk",
    "learning":"desk", "market":"desk", "chat":"desk",
    "market-chart":"desk", "fire":"desk"
  };
  const headings = {
    home:["Your trading desk", "A clear view of what matters right now."],
    bots:["BTC & Gold bots", "Separate accounts. Separate execution. One clear view."],
    analytics:["Performance", "Signed records, without invented profit figures."],
    activity:["Activity & events", "What the models and monitoring services reported."],
    desk:["Advanced desk", "Market charts, research tools and legacy account records."]
  };
  const screenText = $("workspace-subtitle");
  const title = $("workspace-title");
  function route() {
    let hash = decodeURIComponent(location.hash.slice(1) || "");
    let current = known.has(hash) ? hash : (translate[hash] || "home");
    document.body.dataset.screen = current;
    document.querySelectorAll("[data-workspace-link]").forEach(link => {
      const active = link.dataset.workspaceLink === current;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    if (title) title.textContent = headings[current][0];
    if (screenText) screenText.textContent = headings[current][1];
    document.title = headings[current][0] + " · Trading Bot 2.0";
    if (window.scrollY > 100) window.scrollTo({top:0,behavior:"instant"});
  }
  window.addEventListener("hashchange", route);
  route();

  const text = (id, value) => {
    const el = $(id);
    if (el) el.textContent = value;
  };
  const money = value => {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return new Intl.NumberFormat("en-US", {style:"currency", currency:"USD",
      minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
  };
  const humanAge = ts => {
    const t = Date.parse(ts || "");
    if (!Number.isFinite(t)) return "Unavailable";
    const seconds = Math.round((Date.now() - t) / 1000);
    if (seconds < -5 || seconds > 120) return "Stale";
    return seconds < 6 ? "Updated now" : "Updated " + seconds + "s ago";
  };

  const chart = $("home-equity-graph");
  const svgNS = "http://www.w3.org/2000/svg";
  const makeSvg = (tag, attrs) => {
    const e = document.createElementNS(svgNS, tag);
    Object.entries(attrs).forEach(([k,v]) => e.setAttribute(k, String(v)));
    return e;
  };
  function drawTrends(accounts) {
    if (!chart) return;
    chart.replaceChildren();
    const width = 680, height = 152;
    chart.setAttribute("viewBox", "0 0 " + width + " " + height);
    chart.append(makeSvg("line", {x1:8,x2:672,y1:130,y2:130,
       stroke:"#455467","stroke-dasharray":"4 7","stroke-width":1}));
    const series = [];
    for (const key of ["BTC","GOLD"]) {
      const a = accounts[key];
      const raw = a?.equity_points || [];
      const pts = raw.map(p => ({t: Date.parse(p.at), y: Number(p.equity)}))
        .filter(p => Number.isFinite(p.t) && Number.isFinite(p.y) && p.y > 0)
        .sort((x,y) => x.t - y.t).slice(-72);
      if (pts.length < 2 || a.status !== "connected") continue;
      const first = pts[0].y;
      series.push({label:key, color:key==="BTC"?"#69d8ef":"#f0bf78",
        points:pts.map(p=>({t:p.t, index:p.y/first*100}))});
    }
    if (!series.length) {
      chart.setAttribute("aria-label","Not enough verified history to draw equity trends");
      text("home-chart-state","Waiting for verified equity history");
      return;
    }
    const values = series.flatMap(s => s.points.map(p => p.index));
    const min = Math.min(...values), max = Math.max(...values);
    const span = Math.max(0.25,max-min);
    const allT = series.flatMap(s=>s.points.map(p=>p.t));
    const start = Math.min(...allT), end = Math.max(...allT);
    for (const s of series) {
      const points = s.points.map(p =>
        (12+(p.t-start)/Math.max(1,end-start)*656).toFixed(1)+","+
        (121-(p.index-min)/span*105).toFixed(1)).join(" ");
      const line = makeSvg("polyline",{
        points,fill:"none",stroke:s.color,"stroke-width":3,
        "stroke-linecap":"round","stroke-linejoin":"round"
      });
      line.append(makeSvg("title",{}));
      line.firstChild.textContent = s.label+" signed equity indexed to 100 at first observation";
      chart.append(line);
    }
    chart.setAttribute("aria-label",
      "Signed BTC and Gold equity trends indexed independently to 100 at their first plotted observation");
    text("home-chart-state",
      "Signed equity indexed to 100 · "+series.map(s=>s.label).join(" + "));
  }

  function paint(report) {
    if (report?.mode !== "read_only"
        || report?.source !== "isolated_child_accounts") return;
    const asof = Date.parse(report.checked_at || "");
    const validTimestamp = Number.isFinite(asof)
      && Math.abs(Date.now()-asof) <= 120000;
    const a=report.accounts||{};
    const connected=["BTC","GOLD"].filter(k=>a[k]?.status==="connected");
    const signed = connected.length===2 && validTimestamp;
    const workers=["BTC","GOLD"].filter(k=>a[k]?.worker_active===true
      && a[k]?.armed===true && a[k]?.halted===false);
    const available = ["BTC","GOLD"].filter(k=>a[k]?.status==="connected" && validTimestamp);
    const services = ["BTC","GOLD"].flatMap(k=>
      [a[k]?.worker_active,a[k]?.watchdog_active,
       a[k]?.equity_collector_active,a[k]?.alerts_active]);
    const serviceCount = services.filter(x=>x===true).length;
    const circle = $("home-health-ring");
    if (circle) {
      circle.style.setProperty("--health",String(serviceCount/8*100)+"%");
      circle.setAttribute("aria-label",
        serviceCount+" of 8 worker, watchdog, equity and alert services reporting active");
    }
    text("home-service-count",serviceCount+"/8");
    text("home-service-note","Worker, watchdog, equity and alerts · service status only");
    text("home-portfolio-state",validTimestamp?connected.length+
      "/2 signed demo wallets":"Broker snapshot unavailable or stale");
    text("home-updated",humanAge(report.checked_at));
    const total = available.length===2
      ? available.reduce((sum,k)=>sum+Number(a[k].net_equity),0) : NaN;
    const equityReady = signed && ["BTC","GOLD"].every(k=>
      a[k].net_equity!==null && a[k].net_equity!==undefined
      && Number.isFinite(Number(a[k].net_equity)));
    text("home-equity",equityReady?money(total):"—");
    text("home-equity-caption",equityReady
      ? "Sum of two independent signed demo wallets · not profit"
      : "Waiting for both signed isolated-account wallet values");
    text("home-open-positions",signed
      ? String(["BTC","GOLD"].reduce((n,k)=>n+Number(a[k].live_position_count||0),0))
      : "—");
    text("home-open-orders",signed
      ? String(["BTC","GOLD"].reduce((n,k)=>n+Number(a[k].open_orders||0),0))
      : "—");
    text("home-bots-running",workers.length+"/2");
    text("home-operational",workers.length===2 && signed
      ? "Both bots running" : workers.length===2
      ? "Bots running · broker check pending"
      : "Check bot status");
    const hero = $("home-summary");
    if (hero) hero.dataset.health = signed && serviceCount===8 &&
      workers.length===2?"ok":"review";
    for(const key of ["BTC","GOLD"]){
      const k=key.toLowerCase(), item=a[key]||{};
      const brokerOK=validTimestamp && item.status==="connected";
      const botOK=item.worker_active===true && item.armed===true
        && item.halted!==true;
      text("home-"+k+"-status",
        !botOK?"Check bot":!brokerOK?"Broker data unavailable":"Running");
      text("home-"+k+"-equity",
        brokerOK?money(item.net_equity):"—");
      text("home-"+k+"-position",
        brokerOK?item.live_position_count+" open position"+
          (item.live_position_count===1?"":"s"):"Position unavailable");
      const el=$("home-"+k+"-bot");
      if(el)el.dataset.health=botOK && brokerOK?"ok":"review";
    }
    drawTrends(a);
  }

  async function update() {
    try {
      const res = await fetch("/api/isolated/overview",{
        method:"GET",credentials:"same-origin",cache:"no-store",
        signal:AbortSignal.timeout(12000)});
      if(!res.ok)throw Error("Signed broker report unavailable");
      paint(await res.json());
    }catch(_){
      text("home-portfolio-state","Broker data unavailable");
      text("home-equity","—");
      text("home-open-positions","—");
      text("home-open-orders","—");
      text("home-updated","Connection unavailable");
      text("home-operational","Verify account connections");
      for(const key of ["btc","gold"]){
        text("home-"+key+"-equity","—");
        text("home-"+key+"-position","Position unavailable");
        text("home-"+key+"-status","Account unavailable");
      }
      if($("home-summary"))$("home-summary").dataset.health="review";
    }finally{setTimeout(update,35000);}
  }
  update();
})();
