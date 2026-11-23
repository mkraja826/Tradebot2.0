"use strict";
/* Financial evidence graphics and trade explorer.
 * Sources: the signed cached GET-only isolated performance endpoint.
 * No POST, order changes, P&L guessing, remote libraries or source URLs.
 */
(() => {
  const charts=document.getElementById("analytics-cashflow-charts");
  const donutRoot=document.getElementById("analytics-distribution");
  const tradesRoot=document.getElementById("viz-trade-list");
  const count=document.getElementById("viz-trade-count");
  const market=document.getElementById("viz-market");
  const outcome=document.getElementById("viz-outcome");
  const direction=document.getElementById("viz-direction");
  const more=document.getElementById("viz-show-more");
  const short=document.getElementById("performance-24h");
  const long=document.getElementById("performance-7d");
  if(!charts||!donutRoot||!tradesRoot||!count||!market||!outcome||!direction||!more)return;
  let current=null, shown=8;
  const NS="http://www.w3.org/2000/svg";
  const create=(tag,cls,value)=>{
    const n=document.createElement(tag);
    if(cls)n.className=cls;
    if(value!==undefined&&value!==null)n.textContent=String(value);
    return n;
  };
  const svg=(tag,attrs)=>{
    const n=document.createElementNS(NS,tag);
    for(const [k,v] of Object.entries(attrs||{}))n.setAttribute(k,String(v));
    return n;
  };
  const numeric=value=>{
    if(value===null||value===undefined||value==="")return null;
    const v=Number(value);
    return Number.isFinite(v)?v:null;
  };
  const usd=value=>{
    const n=numeric(value);
    if(n===null)return "Unavailable";
    return (n<0?"−":"") + "$" +
      new Intl.NumberFormat("en-US",{minimumFractionDigits:2,maximumFractionDigits:4}).format(Math.abs(n));
  };
  const day=value=>{
    const d=new Date(value);
    return value&&!Number.isNaN(d.getTime())
      ?d.toLocaleString("en-IN",{timeZone:"UTC",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",hour12:false})+" UTC"
      :"Timestamp unavailable";
  };
  const accountTheme={BTC:{label:"Bitcoin",color:"#6bcffa"},
                      GOLD:{label:"Gold",color:"#eebd77"}};
  const outcomes=[
    ["verified_wins","Verified wins","#56d9a6"],
    ["verified_losses","Verified losses","#f38b95"],
    ["verified_breakeven","Verified breakeven","#7cb7b2"],
    ["no_order","No order","#879ab2"],
    ["open_or_unresolved","Open / unresolved","#f3c97a"],
    ["unverified","Not reconciled","#8c8de4"]
  ];
  const activePeriod=()=>long?.getAttribute("aria-pressed")==="true"
    ?"last_7d":"last_24h";

  function cashflowCard(label,account){
    const card=create("article","viz-card viz-"+label.toLowerCase());
    const head=create("div","viz-card-head");
    head.append(create("strong","",accountTheme[label].label+" · wallet postings"),
      create("span","viz-chip",activePeriod()==="last_24h"?"24 HOURS":"7 DAYS"));
    card.append(head);
    const source=account?.cashflow_series;
    const buckets=source?.[activePeriod()];
    if(account?.status!=="complete_broker_window"||
       source?.source!=="complete_signed_wallet_postings"||
       !Array.isArray(buckets)||!buckets.length){
      card.append(create("p","viz-empty","Signed cash-flow history unavailable."));
      return card;
    }
    const values=buckets.map(b=>b.status==="verified_posted_cashflow"
      ?numeric(b.posted_net_usd):null);
    const maximum=Math.max(.01,...values.filter(v=>v!==null).map(Math.abs));
    const plot=create("div","viz-bar-plot");
    plot.setAttribute("role","group");
    plot.setAttribute("aria-label",label+" signed wallet cash flow buckets; select a bar for details");
    const inspect=create("p","viz-inspect","Tap a bar to inspect signed posted cash flows.");
    const line=create("div","viz-zero-axis");
    plot.append(line);
    buckets.forEach((bucket,i)=>{
      const value=values[i],slot=create("div","viz-bar-slot");
      const button=create("button","viz-bar-button");
      button.type="button";
      button.setAttribute("aria-label",bucket.label+" signed net wallet postings "+
        (value===null?"unavailable":usd(value))+
        (bucket.partial?", partial window":""));
      const body=create("span","viz-bar-body");
      const height=value===null?28:Math.max(2,Math.abs(value)/maximum*46);
      body.style.height=height+"%";
      body.classList.add(value===null?"unknown":value<0?"negative":value>0?"positive":"zero");
      if(value<0)body.style.top="50%";
      else body.style.bottom="50%";
      button.append(body);
      const select=()=>{
        plot.querySelectorAll(".viz-bar-button").forEach(e=>e.classList.remove("selected"));
        button.classList.add("selected");
        inspect.textContent=bucket.label+
          (bucket.partial?" · current partial window":"")+
          " · Posted net "+(value===null?"unavailable":usd(value))+
          " · Fees "+usd(bucket.fees_usd)+
          " · Funding "+usd(bucket.funding_usd)+
          " · "+bucket.included_postings+" classified postings"+
          (bucket.unclassified_postings?" · "+bucket.unclassified_postings+" unclassified":"");
      };
      button.addEventListener("click",select);
      slot.append(button,create("small","viz-bar-label",bucket.label.replace(" UTC","")));
      plot.append(slot);
      if(i===buckets.length-1)select();
    });
    card.append(plot,inspect);
    card.append(create("p","viz-footnote",
      "Complete signed broker window · posted amounts, not realized trade P&L"+
      (activePeriod()==="last_7d"?" · today's UTC day is partial":"")));
    return card;
  }

  function donutCard(label,account){
    const card=create("article","viz-card viz-"+label.toLowerCase());
    const head=create("div","viz-card-head");
    head.append(create("strong","",accountTheme[label].label+" · trade outcomes"),
      create("span","viz-chip","7 DAYS"));
    card.append(head);
    const d=account?.trade_distribution;
    if(account?.status!=="complete_broker_window"||!d||!d.counts){
      card.append(create("p","viz-empty","Signed FIRE outcome data unavailable."));
      return card;
    }
    const total=d.total;
    const group=create("div","viz-donut-grid");
    const chart=svg("svg",{viewBox:"0 0 170 170",role:"img",
       "aria-label":label+" "+total+" FIRE receipts, distributed by verified and unverified outcomes"});
    const track=svg("circle",{cx:85,cy:85,r:60,fill:"none",
      stroke:"#273b4a","stroke-width":20});
    chart.append(track);
    const circumference=2*Math.PI*60;
    let previous=0;
    for(const [key,,color] of outcomes){
      const n=d.counts[key]||0;
      if(!n||!total)continue;
      const length=n/total*circumference;
      const arc=svg("circle",{cx:85,cy:85,r:60,fill:"none",
        stroke:color,"stroke-width":20,"stroke-linecap":"butt",
        "stroke-dasharray":length+" "+(circumference-length),
        "stroke-dashoffset":-previous,
        transform:"rotate(-90 85 85)"});
      chart.append(arc);
      previous+=length;
    }
    const center=svg("text",{x:85,y:81,"text-anchor":"middle",
      fill:"#eaf4fe","font-size":30,"font-weight":800});
    center.textContent=total;
    const sub=svg("text",{x:85,y:102,"text-anchor":"middle",
      fill:"#96abba","font-size":10});
    sub.textContent=total===1?"receipt":"receipts";
    chart.append(center,sub);
    const legend=create("div","viz-donut-legend");
    for(const [key,title,color] of outcomes){
      const entry=create("div","viz-legend-entry");
      const dot=create("span","viz-legend-dot");
      dot.style.backgroundColor=color;
      entry.append(dot,create("span","",title),create("strong","",d.counts[key]||0));
      legend.append(entry);
    }
    group.append(chart,legend);
    card.append(group);
    if(d.coverage!=="complete_7d_receipts")
      card.append(create("p","viz-warning",
        "Receipt history exceeds the display cap; these counts are partial."));
    card.append(create("p","viz-footnote",
      "Decision status counts, not a strategy win rate. Unreconciled closed outcomes are not losses."));
    return card;
  }

  const statusFilter=t=>{
    if(outcome.value==="all")return true;
    if(outcome.value==="verified")return t.is_net_realized_pnl===true;
    if(outcome.value==="no_order")return t.reconciliation_status==="no_order";
    if(outcome.value==="open")return t.reconciliation_status==="position_open_or_unresolved";
    if(outcome.value==="unverified")return t.reconciliation_status==="unverified";
    return false;
  };
  function explorer(){
    tradesRoot.replaceChildren();
    const rows=[];
    for(const label of ["BTC","GOLD"]){
      if(market.value!=="all"&&market.value!==label)continue;
      const a=current?.accounts?.[label];
      if(a?.status!=="complete_broker_window")continue;
      for(const t of a.trade_rows||[]){
        if(!statusFilter(t)||direction.value!=="all"&&direction.value!==t.direction)continue;
        rows.push({label,trade:t});
      }
    }
    rows.sort((a,b)=>Date.parse(b.trade.time)-Date.parse(a.trade.time));
    count.textContent=rows.length+" matching FIRE receipts · seven-day broker window"+
      (Object.values(current?.accounts||{}).some(v=>v?.history_truncated)
        ?" · older receipts not fully included":"");
    if(!rows.length){
      tradesRoot.append(create("p","viz-empty","No recorded trades match these filters."));
      more.hidden=true;return;
    }
    rows.slice(0,shown).forEach(({label,trade:t})=>{
      const card=create("details","viz-trade-record");
      const heading=create("summary","viz-trade-summary");
      const marketBadge=create("span","viz-market-badge",label);
      marketBadge.dataset.market=label;
      const summary=create("span","viz-trade-main");
      summary.append(create("strong","",
        (t.direction||"NO ENTRY")+" · "+
        (t.contracts===null||t.contracts===undefined?"Size unverified":t.contracts+" contracts")),
        create("small","",day(t.time)));
      const result=create("span","viz-trade-result");
      const verified=t.is_net_realized_pnl===true &&
        t.reconciliation_status==="broker_reconciled";
      result.dataset.verified=String(verified);
      result.textContent=verified?usd(t.net_realized_pnl_usd):
        t.reconciliation_status==="no_order"?"No order":
        t.reconciliation_status==="position_open_or_unresolved"?"Open / unresolved":
        "Not reconciled";
      heading.append(marketBadge,summary,result);
      card.append(heading);
      const body=create("div","viz-trade-detail");
      const fields=[
        ["Model",t.model||"Unavailable"],
        ["Status",String(t.status||"unknown").replaceAll("_"," ")],
        ["Leverage",t.leverage===null||t.leverage===undefined?"Unverified":t.leverage+"x"],
        ["Reconciliation",String(t.reconciliation_status||"unknown").replaceAll("_"," ")],
        ["Evidence reason",String(t.reason||"Evidence pending").replaceAll("_"," ")],
        ["Net realized P&L",verified?usd(t.net_realized_pnl_usd):"Unverified"]
      ];
      for(const [name,value] of fields){
        const line=create("div","viz-evidence-row");
        line.append(create("span","",name),create("strong","",value));
        body.append(line);
      }
      const note=create("p","viz-footnote",
        "Account-specific immutable FIRE receipt matched against signed broker history. "+
        "This page cannot place trades or change execution policies.");
      body.append(note);
      card.append(body);
      tradesRoot.append(card);
    });
    more.hidden=rows.length<=shown;
    more.textContent="Show "+Math.min(8,rows.length-shown)+" more receipts";
  }
  function draw(){
    charts.replaceChildren();donutRoot.replaceChildren();
    for(const label of ["BTC","GOLD"]){
      const account=current?.accounts?.[label];
      charts.append(cashflowCard(label,account));
      donutRoot.append(donutCard(label,account));
    }
    explorer();
  }
  for(const input of [market,outcome,direction])
    input.addEventListener("change",()=>{shown=8;explorer()});
  more.addEventListener("click",()=>{shown+=8;explorer()});
  for(const control of [short,long]){
    if(control)control.addEventListener("click",()=>draw());
  }
  async function update(){
    let next=28000;
    try{
      const response=await fetch("/api/isolated/performance",{
        method:"GET",credentials:"same-origin",cache:"no-store",
        signal:AbortSignal.timeout(20000)});
      if(!response.ok)throw Error("Signed broker history failed");
      const data=await response.json();
      if(data?.mode!=="read_only"||
         data.source!=="isolated_signed_broker_performance"||
         !data.checked_at||Math.abs(Date.now()-Date.parse(data.checked_at))>450000)
        throw Error("Performance report unavailable or stale");
      current=data;draw();
      if(Object.values(data.accounts||{}).some(a=>a?.status==="loading"))next=3000;
    }catch(_){
      current=null;draw();
      count.textContent="Signed broker performance unavailable; no values assumed.";
    }finally{setTimeout(update,next);}
  }
  update();
})();
