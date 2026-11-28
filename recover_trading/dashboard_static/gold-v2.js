/* Gold V2 read-only sidecar; independent of legacy render and chart. */
(() => {
  "use strict";
  const panel=document.getElementById("goldV2Panel");
  const state=document.getElementById("goldV2State");
  const content=document.getElementById("goldV2Content");
  if(!panel||!state||!content)return;
  let selected="BTCUSD",busy=false,epoch=0;
  const label=x=>x==null?"—":String(x).replaceAll("_"," ");
  const num=x=>typeof x==="number"&&Number.isFinite(x)?x.toLocaleString(undefined,{maximumFractionDigits:3}):"—";
  function element(tag,value,cls){
    const n=document.createElement(tag);
    if(value!=null)n.textContent=value;
    if(cls)n.className=cls;
    return n;
  }
  function table(title,headers,rows){
    content.append(element("h3",title));
    if(!rows.length){content.append(element("p","No observations available.","empty"));return;}
    const wrap=element("div",null,"scroll");
    const t=element("table");const head=element("thead"),tr=element("tr");
    for(const h of headers){const th=element("th",h);th.scope="col";tr.append(th);}
    head.append(tr);t.append(head);const body=element("tbody");
    for(const row of rows){const r=element("tr");for(const v of row)r.append(element("td",v));body.append(r);}
    t.append(body);wrap.append(t);content.append(wrap);
  }
  function hybrid(p){
    if(!["observed","stale"].includes(p?.status))return;
    const q=p.quote_comparison||{},w=p.window_counts||{};
    table("Hybrid research — no actual fills",["Metric","Observation"],[
      ["Worker",label(p.status)+" · "+num(p.age_seconds)+" s old"],
      ["Reference quality",label(p.reference_status)],
      ["Latest signal age (s)",typeof p.signal_observed_at==="number"?num(Math.max(0,Date.now()/1000-p.signal_observed_at)):"—"],
      ["Hybrid status",label(p.hybrid_status)],["Observed quotes",num(p.quote_count)],
      ["Sampled outcomes",num(w.sampled_outcomes)],["Insufficient coverage",num(w.insufficient_quote_coverage)],
      ["Mark basis (bp)",num(q.mark_basis_bps)],["Demo spread (bp)",num(q.demo_spread_bps)]]);
    table("Hybrid sampled comparisons",["Family","Side","Samples","Positive","Mean sampled net (bp)"],
      (p.sampled_comparisons||[]).map(r=>[label(r.family),label(r.direction),num(r.samples),num(r.positive_samples),num(r.mean_sampled_net_bps)]));
    content.append(element("p","Hypothetical sampled quote outcomes, not fills or account returns. Gaps may hide SL/TP crossings.","empty"));
  }
  function mark(p,l){
    if(["observed","stale"].includes(p?.status)){
      const w=p.window_counts||{},q=p.reference_quality||{},m=p.macro||{};
      table("Mark-price hybrid research — no execution",["Metric","Observation"],[
        ["Worker",label(p.status)+" · "+num(p.age_seconds)+" s old"],
        ["5m quality",label(q["300"])],["15m quality",label(q["900"])],["1h quality",label(q["3600"])],
        ["Reference state",label(p.reference_status)],["Hybrid state",label(p.hybrid_status)],
        ["Macro context",label(m.status)],["Macro bias",label(m.bias)],
        ["Quotes",num(p.quote_count)],["Enrolled",num(w.enrolled)],["Resolved samples",num(w.sampled_outcomes)],
        ["Insufficient coverage",num(w.insufficient_quote_coverage)]]);
      table("Mark entry hypotheses",["Family","Side","Macro","Support"],(m.candidates||[]).map(r=>[label(r.family),label(r.direction),label(r.macro_group),num(r.support_index)]));
      table("Mark macro comparisons",["Model","Family","Side","Macro","Samples","Positive","Mean net (bp)"],
        (p.macro_strata||[]).map(r=>[label(r.model_version),label(r.family),label(r.direction),label(r.macro_group),num(r.samples),num(r.positive_samples),num(r.mean_sampled_net_bps)]));
      table("Mark management comparisons",["Model","Family","Side","Policy","Cost (bp)","Pairs","Fixed (bp)","Variant (bp)","Difference (bp)"],
        (p.management_pairs||[]).map(r=>[label(r.model_version),label(r.family),label(r.direction),label(r.policy),num(r.cost_bps),num(r.paired_samples),num(r.mean_fixed_net_bps),num(r.mean_variant_net_bps),num(r.mean_paired_difference_bps)]));
    }else{
      content.append(element("h3","Mark-price hybrid research"));
      content.append(element("p","No mark research observation available.","empty"));
    }
    if(["observed","stale"].includes(l?.status)){
      table("Mark learning — training / holdout",["Model","Family","Side","Macro","Selected policy","Training","Holdout","Status","Holdout 30 bp net"],
        (l.proposals||[]).map(r=>[label(r.model_version),label(r.family),label(r.direction),label(r.macro_group),label(r.selected_on_training),num(r.train_samples),num(r.holdout_samples),label(r.status),num(r.holdout_net_bps_30)]));
      content.append(element("p","Research report · "+label(l.status)+" · Cutoff "+new Date(l.cutoff*1000).toISOString()+" · No automatic promotion.","empty"));
    }else content.append(element("p","No fixed-cutoff mark learning report published.","empty"));
  }
  function render(p){
    content.replaceChildren();
    if(p?.symbol!=="XAUTUSD"||!["observed","stale"].includes(p.status)){
      state.textContent="No Gold V2 worker observation";
      content.append(element("p","The legacy service is independent. Start the separate shadow worker to collect evidence.","empty"));
      hybrid(p?.hybrid);
      mark(p?.mark_hybrid,p?.mark_learning);
      return;
    }
    state.textContent=(p.status==="stale"?"Stale · ":"Observed · ")+num(p.age_seconds)+" s old";
    const grid=element("div",null,"metrics");
    const v=p.validation||{};
    for(const [k,val] of [["Worker",label(p.worker_status)],["Execution",p.execution_enabled===true?"Enabled":p.execution_enabled===false?"Disabled":"Unknown"],["Regime",label(p.market?.regime)],["Validation windows",num(v.observed_nonoverlapping_windows)+" / "+num(v.target_windows)]]){
      const card=element("div",null,"metric");card.append(element("small",k),element("strong",val));grid.append(card);
    }
    content.append(grid);
    if(p.status==="stale")content.append(element("p","Last recorded evidence only; not a current market signal.","empty"));
    const m=p.macro||{};
    table("Fundamental evidence",["Metric","Observation"],[["Macro bias",label(m.bias)],["Broad dollar · 5 observations (%)",num(m.broad_dollar_5obs_pct)],["Real yield · 5 observations (bp)",num(m.real_yield_5obs_bp)]]);
    table("Completed-bar technical evidence",["Frame","Feed","EMA9","EMA21","ATR","RSI","ADX","VWAP20","Rel. volume","Structure"],
      [["300","5m"],["900","15m"],["3600","1h"]].map(([k,name])=>{const f=p.technical?.[k]||{};return [name,label(p.feed_health?.[name]),num(f.ema?.[0]),num(f.ema?.[1]),num(f.atr),num(f.rsi14),num(f.adx),num(f.rolling_vwap20),num(f.relative_volume20),label(f.structure)];}));
    table("Current entry candidates",["Family","Side","Support index","Evidence groups"],(p.candidates||[]).map(r=>[label(r.family),label(r.direction),num(r.support_index),num(r.observed_groups)+" / "+num(r.expected_groups)]));
    content.append(element("p","Support index is an ordinal hypothesis, not a win probability.","empty"));
    table("Account and controller observation",["Field","State"],[["Position",label(p.account?.position_state)],["Bracket",label(p.account?.bracket_state)],["Controller",label(p.controller?.status)],["Entry execution",label(p.controller?.execution_status)],["Management",label(p.controller?.management_status)]]);
    const comparisons=v.combined_comparisons||[];
    table("Paired management research",["Family","Side","Policy","Cost (bp)","Pairs","Fixed net (bp)","Variant net (bp)","Difference (bp)"],comparisons.map(r=>[label(r.family),label(r.direction),label(r.policy),num(r.cost_bps),num(r.paired_samples),num(r.mean_fixed_net_bps_initial_notional),num(r.mean_variant_net_bps_initial_notional),num(r.mean_paired_difference_bps)]));
    hybrid(p.hybrid);
    mark(p.mark_hybrid,p.mark_learning);
    content.append(element("p","Showing "+comparisons.length+" of "+num(v.combined_comparisons_total)+" comparison groups. Normalized initial notional, hypothetical costs, not account returns.","empty"));
  }
  async function refresh(){
    if(selected!=="XAUTUSD"||busy||document.hidden||panel.closest("[data-workspace]")?.hidden)return;
    const ticket=epoch;busy=true;
    try{
      const r=await fetch("/api/gold-v2",{cache:"no-store"});
      if(!r.ok)throw Error("unavailable");
      const p=await r.json();
      if(ticket===epoch&&selected==="XAUTUSD")render(p);
    }catch(_){
      if(ticket===epoch&&selected==="XAUTUSD"){state.textContent="Gold V2 status unavailable";content.replaceChildren();}
    }finally{busy=false;}
  }
  document.addEventListener("recover:market",e=>{
    selected=e.detail;epoch++;panel.hidden=selected!=="XAUTUSD";
    if(panel.hidden){content.replaceChildren();state.textContent="Awaiting observation";}
    else refresh();
  });
  const initial=document.querySelector('[data-symbol][aria-pressed="true"]');
  if(initial){selected=initial.dataset.symbol;panel.hidden=selected!=="XAUTUSD";}
  window.addEventListener("hashchange",refresh);
  document.addEventListener("visibilitychange",refresh);
  setInterval(refresh,15000);refresh();
})();
