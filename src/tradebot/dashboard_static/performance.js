"use strict";
// Signed financial evidence dashboard, read-only. No model calls or order writes.
(() => {
  const root = document.getElementById("performance-grid");
  const sync = document.getElementById("performance-sync");
  const short = document.getElementById("performance-24h");
  const long = document.getElementById("performance-7d");
  if (!root || !sync || !short || !long) return;

  let period="last_24h", current=null;
  const elem=(tag,cls,content)=>{
    const x=document.createElement(tag);
    if (cls)x.className=cls;
    if (content!==undefined && content!==null)x.textContent=String(content);
    return x;
  };
  const amount=(value)=>{
    if (value===null || value===undefined || value==="")return "—";
    const number=Number(value);
    if (!Number.isFinite(number))return "—";
    const abs=Math.abs(number);
    return (number<0?"−":"") + "$"+
      new Intl.NumberFormat("en-US",{minimumFractionDigits:2,
        maximumFractionDigits:4}).format(abs);
  };
  const timeLabel=(value)=>{
    const d=new Date(value);
    if (!value || Number.isNaN(d.getTime()))return "—";
    return d.toLocaleString("en-IN",{timeZone:"UTC",day:"2-digit",
      month:"short",hour:"2-digit",minute:"2-digit",hour12:false})+" UTC";
  };
  const cell=(label,value,description)=>{
    const box=elem("div","perf-stat");
    box.append(elem("small","",label),elem("strong","",value));
    if(description)box.append(elem("span","",description));
    return box;
  };
  const title=(name,text)=>{
    const e=elem("div","perf-section-title");
    e.append(elem("strong","",name),elem("span","",text));
    return e;
  };
  const row=(name,data)=>{
    const r=elem("div","perf-trade");
    const first=elem("div","perf-trade-main");
    first.append(elem("strong","",(data.direction||"NO DIRECTION")+" · "+
      (data.contracts==null?"—":data.contracts+" contracts")));
    first.append(elem("span","",timeLabel(data.time)));
    const second=elem("div","perf-trade-outcome");
    if(data.is_net_realized_pnl===true &&
       data.reconciliation_status==="broker_reconciled"){
      second.append(elem("strong","perf-verified",amount(data.net_realized_pnl_usd)));
      second.append(elem("small","", "Broker-reconciled net USD"));
    } else if(data.reconciliation_status==="no_order"){
      second.append(elem("strong","perf-no-order","NO ORDER"));
      second.append(elem("small","", "AI proposal did not execute"));
    } else {
      second.append(elem("strong","perf-unverified","NOT VERIFIED"));
      const explanation=data.reason==="overlapping_external_postings"?
        "Overlapping broker postings; individual net P&L not verified":
        String(data.reason||"Pending broker evidence").replace(/_/g," ");
      second.append(elem("small","",explanation.slice(0,96)));
    }
    r.append(first,second);
    return r;
  };
  const card=(name,data,stale=false,activity=null)=>{
    const box=elem("article","performance-card "+(name==="GOLD"?"perf-gold":"perf-btc"));
    const header=elem("div","perf-card-heading");
    header.append(elem("h3","",name==="BTC"?"BTCUSD · GPT-6":"XAUTUSD · DeepSeek"),
      elem("span","perf-label",name+" isolated DEMO"));
    box.append(header);
    if(activity?.status==="available"){
      box.append(elem("div","perf-footer",
        "Recorded attempts: "+activity.recorded_attempts+
        " · rejected: "+activity.rejected_attempts+
        " · broker-verified flat: "+activity.verified_flat_attempts+
        " · latest: "+timeLabel(activity.latest_at)+
        " (receipt status only; not trade P&L)"));
    }
    if(stale){
      box.append(elem("div","perf-unavailable",
        "Signed broker performance is older than the freshness window. "+
        "Financial figures are withheld while refreshed evidence is requested."));
      return box;
    }
    if(!data || data.status!=="complete_broker_window"){
      box.append(elem("div","perf-unavailable",
        "Signed broker history unavailable. Performance values are not zero."));
      return box;
    }
    const p=data.wallet?.[period]||{};
    const valid=p.status==="verified_posted_cashflow" &&
      p.posted_net_usd!==null && p.posted_net_usd!==undefined;
    const figures=elem("div","perf-stats");
    figures.append(
      cell("POSTED NET CASHFLOW",valid?amount(p.posted_net_usd):"—",
        "Account wallet · not AI trade P&L"),
      cell("GROSS TRADING CASHFLOW",valid?amount(p.gross_cashflow_usd):"—",
        "Signed settlement postings"),
      cell("PAID FEES / REBATES",valid?amount(p.fees_usd):"—",
        "Signed amounts; negative = cost"),
      cell("FUNDING CASHFLOW",valid?amount(p.funding_usd):"—",
        "Signed amounts, not estimated"));
    box.append(figures);
    if(!valid)box.append(elem("p","perf-unavailable",
      "Signed wallet categories are incomplete; totals intentionally withheld."));
    box.append(title("Verified closed-trade results","Last 7 days · audited subset"));
    const subset=elem("div","perf-subset");
    subset.append(
      cell("RECONCILED TRADES",data.broker_reconciled_closed_trades??"—",
        "All order, fill and funding checks passed"),
      cell("NET REALIZED · VERIFIED SUBSET",
        amount(data.verified_subset_net_usd),"Not whole-account P&L"),
      cell("VERIFIED SUBSET WIN RATE",
        data.verified_subset_win_rate_pct==null?"—":
        Number(data.verified_subset_win_rate_pct).toFixed(1)+"%",
        "Withheld without reconciled closed trades"),
      cell("UNVERIFIED / STILL OPEN",
        data.unverified_or_open_trades??"—",
        "These have no assumed profit or loss"));
    box.append(subset);
    box.append(title("Trade-by-trade verification",
      (data.signed_fill_count??"—")+" signed fills · "+
      (data.signed_wallet_posting_count??"—")+" wallet postings"));
    const trades=data.trade_rows||[];
    const ambiguous=trades.filter(v=>v.reason==="overlapping_external_postings").length;
    if(ambiguous)box.append(elem("p","perf-unavailable",
      ambiguous+" closed trades await independent broker wallet attribution. "+
      "No good/bad verdict or trade P&L has been inferred."));
    if(!trades.length)box.append(elem("div","perf-empty","No FIRE activity in the seven-day window"));
    else{
      const list=elem("div","perf-trade-list");
      trades.slice(0,4).forEach(v=>list.append(row(name,v)));
      box.append(list);
      if(trades.length>4){
        const more=elem("details","perf-more");
        more.append(elem("summary","","Show "+(trades.length-4)+" older trades"));
        trades.slice(4,40).forEach(v=>more.append(row(name,v)));
        box.append(more);
      }
    }
    const footer=elem("div","perf-footer");
    footer.append(elem("span","", "Complete signed 7-day history · "+
      timeLabel(data.as_of)),
      elem("span","","Profitability not established"));
    box.append(footer);
    return box;
  };

  function render(){
    short.setAttribute("aria-pressed",String(period==="last_24h"));
    long.setAttribute("aria-pressed",String(period==="last_7d"));
    root.replaceChildren();
    const accounts=current?.accounts||{};
    const activity=current?.attempt_activity||{};
    const stale=current?.stale===true;
    for(const name of ["BTC","GOLD"])
      root.append(card(name,accounts[name],stale,activity[name]));
    const count=["BTC","GOLD"].filter(k=>
      accounts[k]?.status==="complete_broker_window").length;
    const status=current?.refresh_status==="refreshing"?
      "Refreshing signed histories":stale?
      "Waiting for fresh signed histories":"Signed histories";
    sync.textContent=status+" · "+(stale?0:count)+"/2 fresh · "+
      (current?.checked_at?timeLabel(current.checked_at):
      "No completed broker history yet");
    sync.dataset.state=!stale&&count===2?"ok":"warn";
  }
  short.addEventListener("click",()=>{period="last_24h";render();});
  long.addEventListener("click",()=>{period="last_7d";render();});

  async function refresh(){
    let wait=25000;
    try{
      const response=await fetch("/api/isolated/performance",{
        cache:"no-store",credentials:"same-origin",
        signal:AbortSignal.timeout(20000)});
      if(!response.ok)throw new Error("Performance endpoint unavailable");
      const report=await response.json();
      if(report?.mode!=="read_only" ||
         report.source!=="isolated_signed_broker_performance")
        throw new Error("Unexpected performance data source");
      current=report;
      render();
      if(report.stale===true || report.refreshing===true ||
         !report.checked_at ||
         ["BTC","GOLD"].some(k=>report.accounts?.[k]?.status==="loading"))
        wait=3000;
    }catch(_){
      current={accounts:{}};
      render();
      sync.textContent="Signed performance unavailable";
      sync.dataset.state="warn";
    }finally{
      setTimeout(refresh,wait);
    }
  }
  refresh();
})();
