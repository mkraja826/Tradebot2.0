"use strict";
(() => {
  const get = id => document.getElementById(id);
  const selector = get("fire-market"), canvas = get("market-canvas"), ctx = canvas.getContext("2d");
  const symbols = ["BTCUSD","XAUTUSD"], periods = ["1m","5m","15m","1h"];
  const money = n => n == null || !Number.isFinite(Number(n)) ? "—" :
    Number(n).toLocaleString("en-IN",{maximumFractionDigits:2});
  const clock = n => new Date(n*1000).toLocaleString("en-IN",{timeZone:"Asia/Kolkata",
    month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false})+" IST";
  const timestamp = v => !v ? null : isNaN(Number(v)) ? Date.parse(v)/1000 :
    +v / (+v>1e14?1e6:+v>1e11?1e3:1);
  const data = {}, views = {};
  for (const s of symbols) {
    let saved = {};
    try {saved=JSON.parse(localStorage.getItem("chart-view-"+s))||{};} catch {}
    views[s]={period:periods.includes(saved.period)?saved.period:"5m",
      count:Math.max(12,Math.min(150,Number(saved.count)||48)), anchor:null, inspected:null,fit:true};
  }
  const view = () => views[selector.value];
  function remember(){try{localStorage.setItem("chart-view-"+selector.value,JSON.stringify(view()));}catch{}}
  const btn = (label,fn) => {const b=document.createElement("button");b.textContent=label;b.onclick=fn;return b;};
  let serial=0,replay=null,timer=null,playhead=0,busy=false,visible=[],levels=[],lastHistory="";
  let historyPage=0;
  const periodBar=get("desk-periods");
  for(const p of periods) periodBar.append(btn(p,()=>{leaveReplay();view().period=p;view().anchor=view().inspected=null;
    remember();reload();}));
  function leaveReplay(){get("desk-scorecard").hidden=true;clearInterval(timer);timer=null;replay=null;get("desk-play").textContent="Play replay";}
  function reset(){leaveReplay();view().anchor=view().inspected=null;view().fit=true;reload();}
  selector.addEventListener("change",()=>{leaveReplay();historyPage=0;lastHistory="";reload();});
  get("desk-live").onclick=reset;
  for(const [id,factor] of [["desk-less",1.5],["desk-more",0.67]])get(id).onclick=()=>{
    view().count=Math.min(150,Math.max(12,Math.round(view().count*factor)));view().fit=false;remember();draw();
  };
  get("desk-fit").onclick=()=>{view().anchor=view().inspected=null;view().fit=true;draw();};
  function current(){return replay ? replay.payload : data[selector.value];}
  function feedAge(){
    const q=data[selector.value]?.quote, age=q?.time?Math.max(0,Math.floor(Date.now()/1000-q.time)):null;
    get("desk-age").textContent=replay?"Historical replay":age===null?"Quote unavailable":
      (age>15?"Last quote ":"Updated ")+age+"s ago · Delta Demo";
  }
  function draw(){
    const s=selector.value,v=view(),d=current(),hist=!!replay;
    get("market-title").textContent=(s==="BTCUSD"?"Bitcoin":"Tether Gold")+" perpetual";
    get("desk-player").hidden=!hist;
    for(const b of periodBar.children)b.setAttribute("aria-pressed",String(b.textContent===(hist?d?.period:v.period)));
    const bars=d && d.period===(hist?d.period:v.period)?d.bars||[]:[];
    const end=hist?Math.min(playhead+1,bars.length):v.anchor===null?bars.length:bars.filter(b=>b[0]<=v.anchor).length;
    if(v.anchor!==null && end===0 && !hist) {
      get("desk-inspect").textContent="Inspection is outside the current data window. Tap Live.";
    }
    visible=bars.slice(Math.max(0,end-v.count),end);
    const at=visible.at(-1)?.[0],step={"1m":60,"5m":300,"15m":900,"1h":3600}[d?.period]||300;
    const t=hist?d?.replay:d?.trades?.[0],q=hist?null:d?.quote;
    get("desk-price").textContent=money(hist?visible.at(-1)?.[4]:q?.price);
    feedAge();
    const thesisReady=t && (!hist || timestamp(t.decision_at||t.snapshot_at)<at+step);
    get("desk-thesis").textContent=thesisReady && t.thesis?
      "GPT-6 · "+t.thesis+(t.decision_quote?" · Bid "+money(t.decision_quote.best_bid)+
      " / Ask "+money(t.decision_quote.best_ask)+" at decision":""):"";
    levels=[];
    function level(name,price,color,dash=[]){if(+price>0 && Number.isFinite(+price))levels.push({name,price:+price,color,dash});}
    const position=d?.account?.positions?.[0];
    const entryTime=timestamp(t?.entry?.at);
    const exit=t?.stop_loss_order||t?.take_profit_order;
    if(hist && entryTime && entryTime<at+step && !(exit?.at && exit.at<at+step)){
      level(t.direction+" "+t.contracts+" · Entry",t.entry.price,"#78aef5");
      if(Object.keys(t.exit_order_ids||{}).length===2 && t.protected_at && timestamp(t.protected_at)<at+step){
        level("SL",t.stop_loss,"#ff8792",[5,4]);level("TP",t.take_profit,"#70dcad",[5,4]);
      }
    } else if(!hist && position){
      level((+position.size>0?"Long ":"Short ")+Math.abs(position.size)+" · Entry",position.entry_price,"#78aef5");
      for(const o of d.account.exits||[])if(o.side===(+position.size>0?"sell":"buy"))
        level(o.kind==="stop_loss_order"?"SL":"TP",o.price,o.kind==="stop_loss_order"?"#ff8792":"#70dcad",[5,4]);
    }
    level("Mark",q?.mark,"#dcb76d",[2,5]);
    const executionLevels=levels.length;
    const history=hist?(thesisReady?t?.indicators?.historical_levels:null):d?.historical_levels;
    if(history){
      const labels={day:"Day",previous_day:"Previous day",week:"Week",previous_week:"Previous week",
        month:"Month",previous_month:"Previous month"};
      for(const [key,label] of Object.entries(labels)){
        const period=history.periods[key];
        level(label+" high",period?.high,"#ba90ad",[3,5]);
        level(label+" low",period?.low,"#87aaca",[3,5]);
      }
      for(const [frame,swing] of Object.entries(history.swings)){
        level(frame+" support",swing.support?.price,"#79baa5",[5,4]);
        level(frame+" resistance",swing.resistance?.price,"#d18c89",[5,4]);
      }
    }
    get("desk-levels").replaceChildren(...levels.map(l=>btn(l.name+" "+money(l.price),()=>{
      get("desk-inspect").textContent=l.name+" "+money(l.price)+(q?.mark?" · "+((l.price/+q.mark-1)*100).toFixed(2)+"% from mark":"");
    })));
    if(history){
      const range=document.createElement("small");
      const missing=Object.values(history.periods).filter(p=>p.bars<p.expected).length;
      range.textContent=(history.scan_from?
        (history.scanned_to_launch?"History scanned from ":"Loading older candles · scanned from ")+
        new Date(history.scan_from*1000).toISOString().slice(0,10):"Waiting for historical candles")+
        " · UTC · 5m closes"+(missing?" · "+missing+" incomplete periods":"");
      get("desk-levels").append(range);
    }
    const w=canvas.clientWidth,h=canvas.clientHeight,scale=devicePixelRatio||1;
    if(canvas.width!==Math.round(w*scale)||canvas.height!==Math.round(h*scale)){
      canvas.width=Math.round(w*scale);canvas.height=Math.round(h*scale);
    }
    ctx.setTransform(scale,0,0,scale,0,0);ctx.clearRect(0,0,w,h);
    if(!visible.length){if(v.anchor===null)get("desk-inspect").textContent="";get("desk-outcome").textContent="";ctx.fillStyle="#afb9c3";ctx.fillText("Waiting for "+s+" candles",12,32);return;}
    const plot=w-74,dx=plot/visible.length;
    const prices=visible.flatMap(b=>[b[2],b[3]]);
    if(v.fit)prices.push(...levels.slice(0,executionLevels).map(l=>l.price));
    const lo=Math.min(...prices),hi=Math.max(...prices),pad=(hi-lo)*.1||1;
    const y=p=>12+(hi+pad-p)/(hi-lo+2*pad)*(h-44);
    const x=i=>(i+.5)*dx;
    ctx.font="11px system-ui";ctx.lineWidth=1;
    for(let i=0;i<5;i++){
      const p=lo+(hi-lo)*i/4;ctx.strokeStyle="#29333b";ctx.beginPath();ctx.moveTo(0,y(p));ctx.lineTo(plot,y(p));ctx.stroke();
      ctx.fillStyle="#9fadb9";ctx.fillText(money(p),plot+4,y(p)+4);
    }
    visible.forEach(([ts,o,high,low,c],i)=>{
      ctx.fillStyle=ctx.strokeStyle=c>=o?"#72d6b1":"#ea8491";ctx.beginPath();ctx.moveTo(x(i),y(high));
      ctx.lineTo(x(i),y(low));ctx.stroke();ctx.fillRect(i*dx+dx*.17,Math.min(y(o),y(c)),Math.max(1,dx*.66),Math.max(1,Math.abs(y(c)-y(o))));
    });
    for(const l of levels){const py=y(l.price);if(py<5||py>h-20)continue;
      ctx.strokeStyle=ctx.fillStyle=l.color;ctx.setLineDash(l.dash);ctx.beginPath();ctx.moveTo(0,py);ctx.lineTo(plot,py);ctx.stroke();ctx.setLineDash([]);
      ctx.fillText(l.name,4,Math.max(12,py-3));
    }
    const markers=[[t?.at,"Press"],[timestamp(t?.decision_at),"Decision"],[entryTime,"Fill"],[exit?.at,"Exit"]];
    markers.forEach(([when,label],n)=>{
      const i=visible.findIndex(b=>when>=b[0] && when<b[0]+step);if(i<0)return;
      ctx.fillStyle="#ecdab5";ctx.fillText(label,Math.min(plot-30,Math.max(1,x(i)-10)),14+n*12);
    });
    const chosen=visible.find(b=>b[0]===v.inspected);
    if(chosen){const i=visible.indexOf(chosen);ctx.strokeStyle="#f0ebdc";ctx.beginPath();ctx.moveTo(x(i),4);ctx.lineTo(x(i),h-22);ctx.stroke();}
    const bar=chosen||visible.at(-1);
    get("desk-inspect").textContent=clock(bar[0])+" · O "+money(bar[1])+"  H "+money(bar[2])+"  L "+money(bar[3])+"  C "+money(bar[4]);
    ctx.fillStyle="#9fadb9";ctx.fillText(clock(visible[0][0]),4,h-5);
    get("desk-outcome").textContent=hist && exit && exit.at<at+step?
      (t.stop_loss_order?"Stop-loss":"Take-profit")+" filled at "+money(exit.price)+" · "+clock(exit.at)+(entryTime?" · Held "+Math.round((exit.at-entryTime)/60)+" min":"")
      +(exit.commission!=null?" · Exit commission "+exit.commission:""):
      hist && playhead===bars.length-1?"End of available replay · "+(t?.status||"")+
        (exit?"":" · Exit fill unverified"):"";
  }
  function positions(){
    const root=get("desk-positions");root.replaceChildren();
    for(const s of symbols){const d=data[s],a=d?.account,p=a?.positions?.[0];
      const label=s+" · "+(!a?"Account data unavailable":!p?"Flat":(+p.size>0?"Long ":"Short ")+Math.abs(p.size)+
        " @ "+money(p.entry_price)+" · Mark "+money(d.quote?.mark)+" · Unrealised P&L "+money(p.unrealized_pnl));
      root.append(btn(label,()=>{if(selector.disabled)return;selector.value=s;selector.dispatchEvent(new Event("change"));}));
    }
  }
  function showScorecard(t){
    const root=get("desk-scorecard"), c=t.scorecard;
    root.replaceChildren();root.hidden=!c;
    if(!c)return;
    const title=document.createElement("h3");title.textContent=selector.value+" · FIRE scorecard";root.append(title);
    const fmt=(n,digits=4)=>n==null?"—":Number(n).toLocaleString("en-IN",{maximumFractionDigits:digits});
    const metric=(label,value)=>{const p=document.createElement("p");p.textContent=label+" · "+value;root.append(p);};
    metric("Decision", [t.direction,t.contracts!=null?t.contracts+" contracts":null,t.thesis||t.reason_code||t.status].filter(Boolean).join(" · "));
    metric("GPT-6 response",t.model_latency_ms==null?"Unavailable":fmt(t.model_latency_ms/1000,2)+" s");
    metric("Snapshot bid / ask",fmt(c.quote.best_bid)+" / "+fmt(c.quote.best_ask));
    metric("1h return / volatility",fmt(c.return_1h_pct)+"% / "+fmt(c.realized_vol_1h_pct)+"%");
    if(t.indicators){
      const i=t.indicators;
      metric("At decision · 15m / 1h EMA slope", (i.ema_15m?.slope??"—")+" / "+(i.ema_1h?.slope??"—"));
      metric("Session VWAP / 5m ATR",fmt(i.session_vwap)+" / "+fmt(i.atr_5m));
      if(i.since_exit)metric("Move since broker exit (ATR)",fmt(i.since_exit.move_atr));
    }
    metric("Stop / target",fmt(t.stop_loss)+" / "+fmt(t.take_profit));
    metric("Entry fill",fmt(t.entry?.price));
    const exit=t[c.exit];
    metric("Exit",exit?(c.exit==="stop_loss_order"?"Stop-loss":"Take-profit")+" filled @ "+fmt(exit.price):"No confirmed bracket fill");
    metric("Fees / Provisional P&L (USD, excludes funding; NOT net realized P&L)",fmt(c.fees_usd,6)+" / "+fmt(c.provisional_pnl_after_order_fees_usd,6));
    metric("Price move from snapshot midpoint", [5,15,30].map(m=>m+"m "+(c.moves[m]==null?"—":fmt(c.moves[m])+"%")).join(" · "));
  }
  for(const [id,delta] of [["desk-newer",-1],["desk-older",1]]){
    get(id).onclick=()=>{leaveReplay();historyPage=Math.max(0,historyPage+delta);lastHistory="";reload();};
  }
  function history(){
    const rows=data[selector.value]?.trades||[];
    get("desk-newer").hidden=historyPage===0;get("desk-older").hidden=rows.length<40;
    const key=selector.value+historyPage+rows.map(t=>t.id+t.status).join();
    if(key===lastHistory)return;lastHistory=key;
    const root=get("desk-history");root.replaceChildren();
    for(const t of rows)root.append(btn(clock(t.at)+" · "+(t.direction||"FIRE")+" · "+t.status.replaceAll("_"," ")+" · View",()=>{
      leaveReplay();replay={id:t.id};view().inspected=null;reload();
    }));
    if(!rows.length)root.textContent="No FIRE presses on this page.";
  }
  async function request(s,p,id,summary=false){
    const params=new URLSearchParams({symbol:s,period:p,page:String(historyPage)});if(id)params.set("trade",id);if(summary)params.set("summary","1");
    const response=await fetch("/api/chart-desk?"+params,{cache:"no-store"});
    if(!response.ok)throw Error();return response.json();
  }
  async function reload(){
    const n=++serial,s=selector.value,p=view().period;
    busy=true;get("desk-outcome").textContent="";get("desk-inspect").textContent="";draw();
    try{
      if(replay){const d=await request(s,p,replay.id);if(n!==serial)return;replay.payload=d;showScorecard(d.replay);
        playhead=Math.max(0,d.bars.findIndex(b=>b[0]+({"1m":60,"5m":300,"15m":900,"1h":3600}[d.period])>d.replay.at));
        get("desk-scrub").max=Math.max(0,d.bars.length-1);get("desk-scrub").value=playhead;draw();
      }else await Promise.all(symbols.map(async sym=>{
        try{const d=await request(sym,views[sym].period,null,sym!==s);if(n!==serial)return;
          if(!d.quote && data[sym]?.quote)d.quote=data[sym].quote;
          if(sym!==s){data[sym]={...data[sym],account:d.account,quote:d.quote};}
          else {if(!d.bars.length && data[sym]?.period===d.period)d.bars=data[sym].bars;
          data[sym]=d;}
        }catch{if(n===serial && data[sym])data[sym].account=null;}
        if(n===serial){positions();history();draw();}
      }));
    }catch{if(n===serial)get("desk-outcome").textContent="Replay data unavailable.";}
    finally{if(n===serial)busy=false;}
  }
  get("desk-scrub").oninput=e=>{playhead=+e.target.value;draw();};
  get("desk-play").onclick=()=>{if(timer){clearInterval(timer);timer=null;get("desk-play").textContent="Play replay";return;}
    if(playhead>=+get("desk-scrub").max)playhead=0;
    get("desk-play").textContent="Pause";timer=setInterval(()=>{if(playhead>=+get("desk-scrub").max){get("desk-play").click();return;}
      get("desk-scrub").value=++playhead;draw();},550);};
  let drag=null,hold=null;
  function inspect(px){const i=Math.max(0,Math.min(visible.length-1,Math.floor(px/(canvas.clientWidth-74)*visible.length)));
    if(visible[i]){view().inspected=visible[i][0];view().anchor=visible.at(-1)[0];draw();}}
  canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);drag={x:e.clientX,end:visible.at(-1)?.[0],moved:false};
    hold=setTimeout(()=>inspect(e.clientX-canvas.getBoundingClientRect().left),350);};
  canvas.onpointermove=e=>{if(!drag||replay||Math.abs(e.clientX-drag.x)<6)return;
    clearTimeout(hold);drag.moved=true;const bars=data[selector.value]?.bars||[],i=bars.findIndex(b=>b[0]===drag.end);
    const delta=Math.round((e.clientX-drag.x)*visible.length/(canvas.clientWidth-74));
    view().anchor=bars[Math.max(0,Math.min(bars.length-1,i-delta))]?.[0];view().fit=false;draw();};
  canvas.onpointerup=e=>{clearTimeout(hold);if(drag&&!drag.moved)inspect(e.clientX-canvas.getBoundingClientRect().left);drag=null;};
  canvas.onpointercancel=()=>{clearTimeout(hold);drag=null;};
  canvas.onkeydown=e=>{if(!["ArrowLeft","ArrowRight"].includes(e.key)||!visible.length)return;e.preventDefault();
    const idx=visible.findIndex(b=>b[0]===view().inspected);view().inspected=visible[Math.max(0,Math.min(visible.length-1,
      (idx<0?visible.length-1:idx)+(e.key==="ArrowLeft"?-1:1)))][0];view().anchor=visible.at(-1)[0];draw();};
  get("fire-preview").addEventListener("click",()=>{if(replay){leaveReplay();reload();}});
  new ResizeObserver(draw).observe(canvas);reload();
  setInterval(()=>{if(!busy&&!replay&&!document.hidden)reload();},5000);setInterval(feedAge,1000);
})();
