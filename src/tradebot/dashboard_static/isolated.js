"use strict";
// Autonomous isolated-account view. Read-only GETs; no order or model calls.
(() => {
  const root = document.getElementById("isolated-grid");
  const sync = document.getElementById("isolated-sync");
  if (!root || !sync) return;

  const make = (tag, cls, value) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (value !== undefined && value !== null) e.textContent = String(value);
    return e;
  };
  const fmt = (value, precision = 2) => {
    if (value === null || value === undefined || value === "") return "—";
    const number = Number(value);
    return Number.isFinite(number)
      ? new Intl.NumberFormat("en-US", {maximumFractionDigits:precision,
          minimumFractionDigits:precision}).format(number) : "—";
  };
  const date = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? "—"
      : d.toLocaleString("en-IN", {timeZone:"UTC", day:"2-digit", month:"short",
          hour:"2-digit", minute:"2-digit", hour12:false}) + " UTC";
  };
  const pill = (label, state) => make("span","iso-pill "+state,label);
  const flag = value => value === true ? "Reporting" : "Unavailable";
  const infoRow = (label, value) => {
    const r=make("div","iso-line");
    r.append(make("span","",label),make("strong","",value));
    return r;
  };
  const stat = (label, value, hint) => {
    const box=make("div","iso-stat");
    box.append(make("small","",label),make("strong","",value));
    if (hint) box.append(make("span","",hint));
    return box;
  };
  const sparkline = (points, variant) => {
    const wrap=make("div","iso-curve");
    const title=make("div","iso-curve-caption","Signed equity observations · NOT realized P&L");
    wrap.append(title);
    if (!Array.isArray(points) || points.length < 2) {
      wrap.append(make("div","iso-empty","Not enough authentic equity readings for a trend"));
      return wrap;
    }
    const numbers=points.map(v => Number(v.equity));
    if (numbers.some(v => !Number.isFinite(v))) {
      wrap.append(make("div","iso-empty","Equity history unavailable"));
      return wrap;
    }
    const low=Math.min(...numbers), high=Math.max(...numbers);
    const range=Math.max(high-low,Math.abs(high)*0.0001,0.0001);
    const path=numbers.map((v,i) => {
      const x=8+(i/(numbers.length-1))*304;
      const y=60-((v-low)/range)*45;
      return x.toFixed(1)+","+y.toFixed(1);
    }).join(" ");
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
    svg.setAttribute("viewBox","0 0 320 70");
    svg.setAttribute("role","img");
    svg.setAttribute("aria-label",variant+" signed demo equity observation trend");
    const guide=document.createElementNS("http://www.w3.org/2000/svg","line");
    guide.setAttribute("x1","0");guide.setAttribute("x2","320");
    guide.setAttribute("y1","61");guide.setAttribute("y2","61");
    guide.setAttribute("class","iso-guide");
    const poly=document.createElementNS("http://www.w3.org/2000/svg","polyline");
    poly.setAttribute("points",path);poly.setAttribute("class","iso-spark");
    svg.append(guide,poly);
    wrap.append(svg,make("small","",points.length+" verified readings · Last "+date(points.at(-1)?.at)));
    return wrap;
  };

  const receipt = (record) => {
    const row=make("div","iso-receipt");
    const head=make("div","iso-receipt-head");
    const status=String(record.status||"unknown").replace(/_/g," ");
    head.append(make("strong","",status),make("time","",date(record.time)));
    const bits=[];
    if (record.direction) bits.push(record.direction);
    if (Number.isFinite(Number(record.contracts))) bits.push(record.contracts+" contracts");
    if (record.selected_leverage) bits.push(record.selected_leverage+"x");
    if (record.orders_submitted===true) bits.push("Broker order submitted");
    if (record.orders_submitted===false) bits.push("No broker order");
    row.append(head,make("p","",bits.join(" · ")||"Details unavailable"));
    if (record.status==="protected_active")
      row.append(pill(record.protection_verified===true && record.liquidation_verified===true
        ? "SL/TP + liquidation verified" : "Protection unverified",
        record.protection_verified===true && record.liquidation_verified===true ? "ok" : "bad"));
    if (record.reason_code) row.append(make("small","iso-warning","Reason: "+record.reason_code));
    return row;
  };

  function renderAccount(label, item) {
    const card=make("article","isolated-card "+(label==="BTC"?"iso-btc":"iso-gold"));
    const head=make("div","iso-account-head");
    const icon=make("div","iso-account-symbol",label==="BTC"?"₿":"Au");
    const name=make("div","iso-account-name");
    name.append(make("small","",label==="BTC"?"BITCOIN · ISOLATED DEMO":"TETHER GOLD · ISOLATED DEMO"),
      make("h3","",label==="BTC"?"BTCUSD":"XAUTUSD"),
      make("span","",label==="BTC"?"GPT-6 decision engine":"DeepSeek V4.1 Flash"));
    head.append(icon,name);
    const states=make("div","iso-states");
    states.append(
      pill(item.worker_active===true?"Bot service running":"Bot service unavailable",
        item.worker_active===true?"ok":"bad"),
      pill(item.halted===true?"Incident halt":item.armed===true?"Armed":"Disarmed",
        item.halted===true?"bad":item.armed===true?"ok":"warn"),
      pill(item.status==="connected"?"Broker verified":"Broker data unavailable",
        item.status==="connected"?"ok":"warn"));
    card.append(head,states);
    const grid=make("div","iso-stats");
    grid.append(
      stat("NET EQUITY · DEMO",item.status==="connected"&&item.net_equity!==null?
        "$"+fmt(item.net_equity):"—","Broker wallet, not P&L"),
      stat("OPEN POSITIONS",item.status==="connected"?item.live_position_count:"—","Signed broker read"),
      stat("PENDING / PROTECTIVE ORDERS",item.status==="connected"?item.open_orders:"—",
        "Does not distinguish stop and target"),
      stat("FIRE RECEIPTS",item.fire?.total??"—","Includes rejected and closed attempts"));
    card.append(grid);
    if (item.status==="connected" && Array.isArray(item.positions)) {
      const positions=make("div","iso-positions");
      positions.append(make("h4","",item.positions.length?"Broker-reported positions":"Broker reports no open positions"));
      item.positions.forEach(p => positions.append(infoRow(
        p.side+" · "+p.size+" "+(p.symbol||"contracts"),
        (p.entry!==null ? "Entry $"+fmt(p.entry) : "Entry —")+
        (p.unrealized_pnl!==null && p.unrealized_pnl!==undefined
          ? " · Unrealized $"+fmt(p.unrealized_pnl) : ""))));
      card.append(positions);
    } else card.append(make("p","iso-unavailable",
      "Signed child-account position data unavailable. Do not interpret as flat."));
    if (item.reconciliation_warning) card.append(
      make("p","iso-unavailable",item.reconciliation_warning));
    card.append(sparkline(item.equity_points,label));
    const monitor=make("div","iso-monitor");
    monitor.append(infoRow("Watchdog",flag(item.watchdog_active)),
      infoRow("Equity collector",flag(item.equity_collector_active)),
      infoRow("Telegram alerts",flag(item.alerts_active)));
    const health=item.equity_health||{};
    monitor.append(infoRow("Daily / weekly checkpoint",
      (health.daily_checkpoint||"unavailable")+" / "+(health.weekly_checkpoint||"unavailable")));
    card.append(monitor);
    const history=make("div","iso-history");
    const hh=make("div","iso-history-head");
    hh.append(make("h4","","Recent execution receipts"),
      make("small","",item.attempts?.total==null?"Attempt history unavailable":item.attempts.total+" attempts"));
    history.append(hh);
    const recent=item.fire?.recent||[];
    if (recent.length) recent.slice(0,3).forEach(r=>history.append(receipt(r)));
    else history.append(make("div","iso-empty","No verified FIRE records to show"));
    card.append(history);
    const foot=make("div","iso-foot");
    foot.append(make("span","", "Realized net P&L: Pending broker-fill reconciliation"));
    foot.append(make("span","", "Broker read: "+date(item.broker_checked_at)));
    card.append(foot);
    return card;
  }

  function renderReport(report) {
    if (!report || report.mode!=="read_only"
        || report.source!=="isolated_child_accounts") throw new Error("Unverified source");
    const stale=(!report.checked_at || (Date.now()-Date.parse(report.checked_at)>110000));
    if (stale) throw new Error("Signed account report stale");
    root.replaceChildren();
    for (const label of ["BTC","GOLD"]) {
      const item=report.accounts?.[label];
      root.append(item?.status==="loading"
        ? make("article","isolated-card","Waiting for "+label+" signed broker snapshot…")
        : renderAccount(label,item||{status:"unavailable"}));
    }
    const accounts=["BTC","GOLD"].map(k=>report.accounts?.[k]);
    const connected=accounts.filter(a=>a?.status==="connected").length;
    const running=accounts.filter(a=>a?.worker_active===true && a?.halted===false).length;
    const loading=accounts.some(a=>a?.status==="loading");
    sync.textContent=loading ? "Checking signed broker accounts…" :
      connected+"/2 signed broker accounts · "+date(report.checked_at);
    sync.dataset.state=connected===2?"ok":"warn";
    const header=document.getElementById("runtime-status");
    const pillHead=document.getElementById("runtime-pill");
    if (header) header.textContent=loading?"VERIFYING TWO ACCOUNTS" :
      (running===2 && connected===2 ? "BTC + GOLD · ACTIVE" :
       running===2 ? "BOT DATA NEEDS VERIFICATION" : "AUTONOMOUS SERVICE NEEDS REVIEW");
    if (pillHead) pillHead.dataset.state=running===2 && connected===2?"running":"stale";
  }

  async function updateIsolated() {
    let retry=15000;
    try {
      const response=await fetch("/api/isolated/overview",{
        credentials:"same-origin",cache:"no-store",signal:AbortSignal.timeout(19000)});
      if (!response.ok) throw new Error("Isolated accounts endpoint failed");
      const data=await response.json();
      renderReport(data);
      if (data.accounts?.BTC?.status==="loading"
          || data.accounts?.GOLD?.status==="loading") retry=2500;
    } catch (_) {
      root.replaceChildren(make("div","iso-unavailable",
        "Isolated account data currently unavailable. Existing trading and protection services operate separately."));
      sync.textContent="Account monitoring data unavailable";
      sync.dataset.state="warn";
      const header=document.getElementById("runtime-status");
      const pillHead=document.getElementById("runtime-pill");
      if (header) header.textContent="ACCOUNT DATA CONNECTION LOST";
      if (pillHead) pillHead.dataset.state="stale";
    } finally {
      setTimeout(updateIsolated,retry);
    }
  }
  updateIsolated();
})();
