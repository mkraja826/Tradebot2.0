"use strict";
(()=>{
 const id=x=>document.getElementById(x),root=id("marketChart"),L=window.LightweightCharts;
 let symbol=document.querySelector("[data-symbol][aria-pressed=true]")?.dataset.symbol||"BTCUSD",frame="5m",packet=null,selected=new Set(),generation=0,busy=false,levels=true,showFills=true,overlays=new Map(),dockKey="",chart=null,candles=null,volume=null,markers=null,priceLines=[],studySeries=[],studyKey="",crossTime=null,displayed=[],rowsByTime=new Map();
 const colors={up:"#29c99a",down:"#f27783",grid:"#303943",muted:"#a1aebb"};
 const fmt=(n,d=2)=>Number.isFinite(n)?n.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}):"—";
 function visible(){return !root.closest("[data-workspace]").hidden}
 const lineStyle={entry:["ENTRY","#83a9ff"],mark:["MARK","#c4ccd5"],stop:["SL","#f27783"],target:["TP","#29c99a"],break_even:["BE est.","#e6b65c"]};
 function overlay(){return overlays.get(symbol)||{}}
 function isFresh(o){const age=Date.now()/1000-o.observed;return Number.isFinite(o.observed)&&age>=-5&&age<=180}
 function dock(){
   const o=overlay(),fresh=isFresh(o),wrap=id("positionDock"),key=JSON.stringify([symbol,fresh,o.observed,o.status,o.direction,o.contracts,o.unrealized_pnl,o.lines,o.bracket_state,o.management]);if(key===dockKey)return;dockKey=key;wrap.replaceChildren();
   const text=(tag,value,cls)=>{const n=document.createElement(tag);n.textContent=value;if(cls)n.className=cls;return n};
   if(!fresh||o.status!=="position_observed"){wrap.append(text("p",fresh&&o.status==="flat"?"No open position":"Position observation unavailable or stale","caution"));return}
   wrap.append(text("strong",o.direction+" · "+o.contracts+" contracts","dock-side "+(o.direction==="LONG"?"gain":"loss")),text("small","Exchange unrealized P&L","dock-label"),text("strong",o.unrealized_pnl==null?"—":fmt(Number(o.unrealized_pnl))+" USD","dock-pnl "+(Number(o.unrealized_pnl)>=0?"gain":"loss")));
   const list=document.createElement("dl");list.className="dock-fields";
   for(const l of o.lines||[]){const style=lineStyle[l.kind];if(!style)continue;list.append(text("dt",style[0]),text("dd",fmt(l.price)))}
   list.append(text("dt","Bracket"),text("dd",o.bracket_state==="matching_legs_observed"?"Matching legs":"Unverified"),text("dt","Latest management"),text("dd",[o.management?.action,o.management?.status].filter(Boolean).join(" · ").replaceAll("_"," ")||"—"));
   wrap.append(list,text("p","Observed "+new Date(o.observed*1000).toLocaleTimeString(),"empty"));
 }
 const defs={ema9:[["ema9","EMA 9","#83a9ff"]],ema20:[["ema20","EMA 20","#e6b65c"]],ema50:[["ema50","EMA 50","#b79af6"]],ema200:[["ema200","EMA 200","#ef9e70"]],bb:[["bb_upper","BB upper","#779bc9"],["bb_mid","BB mid","#779bc9"],["bb_lower","BB lower","#779bc9"]],vwap:[["vwap","UTC VWAP","#39cdb7"]],sr:[["support","Prior low","#29c99a"],["resistance","Prior high","#f27783"]],rsi:[["rsi","RSI 14","#b79af6"]],macd:[["macd","MACD","#83a9ff"],["macd_signal","Signal","#e6b65c"],["macd_hist","Histogram","#29c99a"]],atr:[["atr","ATR 14","#e6b65c"]]};
 const lower=new Set(["rsi","macd","atr"]);

 function readout(t){
   const row=rowsByTime.get(t)||packet?.candles?.at(-1),s=(packet?.studies||[]).find(x=>x.time===row?.time);
   id("chartReadout").textContent=row?new Date(row.time*1000).toLocaleString()+" · O "+fmt(row.open)+" · H "+fmt(row.high)+" · L "+fmt(row.low)+" · C "+fmt(row.close)+" · V "+fmt(row.volume,0):"Open · High · Low · Close · Volume";
   id("studyLegend").replaceChildren(...[...selected].flatMap(k=>defs[k]).map(([key,label])=>{const n=document.createElement("span");n.textContent=label+" "+fmt(s?.[key]);return n}));
 }
 function dispose(){if(chart)chart.remove();chart=null;candles=null;volume=null;markers=null;priceLines=[];studySeries=[];studyKey="";root.replaceChildren();}
 function ensure(){
   if(chart)return true;
   if(!L?.createChart||!L.CandlestickSeries){id("marketChartStatus").textContent="Chart library unavailable · deployment asset missing";return false}
   chart=L.createChart(root,{autoSize:true,localization:{locale:"en-US"},layout:{background:{type:L.ColorType.Solid,color:"#141a22"},textColor:colors.muted,attributionLogo:true,panes:{separatorColor:"#303943",separatorHoverColor:"#49586a",enableResize:true}},grid:{vertLines:{color:colors.grid},horzLines:{color:colors.grid}},rightPriceScale:{borderColor:colors.grid,minimumWidth:74,scaleMargins:{top:.12,bottom:.24}},timeScale:{borderColor:colors.grid,timeVisible:true,secondsVisible:false,rightOffset:5,barSpacing:7,minBarSpacing:1},crosshair:{mode:L.CrosshairMode.Normal},handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},handleScale:{axisPressedMouseMove:true,mouseWheel:true,pinch:true}});
   candles=chart.addSeries(L.CandlestickSeries,{upColor:colors.up,downColor:colors.down,wickUpColor:colors.up,wickDownColor:colors.down,borderVisible:false,priceLineVisible:false,lastValueVisible:true});
   volume=chart.addSeries(L.HistogramSeries,{priceScaleId:"volume",priceFormat:{type:"volume"},lastValueVisible:false,priceLineVisible:false});
   volume.priceScale().applyOptions({scaleMargins:{top:.83,bottom:0}});
   markers=L.createSeriesMarkers(candles,[]);
   chart.subscribeCrosshairMove(p=>{crossTime=typeof p.time==="number"?p.time:null;readout(crossTime)});
   return true;
 }
 function withGaps(rows,step,map){
   const result=[];let previous=null;
   for(const row of rows){if(previous!==null&&row.time>previous+step)result.push({time:previous+step});result.push(map(row));previous=row.time}
   return result;
 }
 function overlayView(){
   dock();if(!chart||!packet)return;
   for(const line of priceLines)candles.removePriceLine(line);priceLines=[];
   const o=overlay(),fresh=isFresh(o),live=levels&&fresh&&o.status==="position_observed";
   const atLatest=chart.timeScale().scrollPosition()>=-2;
   if(live&&atLatest)for(const l of o.lines||[]){if(!lineStyle[l.kind]||!Number.isFinite(l.price)||l.price<=0)continue;const [title,color]=lineStyle[l.kind];priceLines.push(candles.createPriceLine({price:l.price,color,lineWidth:1,lineStyle:L.LineStyle.Dashed,axisLabelVisible:true,title}));}
   const times=new Set(packet.candles.map(r=>r.time)),fills=showFills?(o.fills||[]).filter(f=>Number.isFinite(f.time)&&Number.isFinite(f.price)&&times.has(Math.floor(f.time/packet.step)*packet.step)):[];
   markers.setMarkers(fills.map(f=>({time:Math.floor(f.time/packet.step)*packet.step,position:f.side==="buy"?"belowBar":"aboveBar",color:f.side==="buy"?colors.up:colors.down,shape:f.side==="buy"?"arrowUp":"arrowDown",text:(f.kind==="entry"?"E":f.kind==="exit"?"X":"Fill")+" "+fmt(f.price)})).sort((a,b)=>a.time-b.time));
   id("chartOverlayNote").textContent=fills.length+" recorded fills in loaded archive · "+(live&&atLatest?"Current snapshot price lines, not historical levels":!atLatest?"Current levels hidden while panning":!fresh?"Position snapshot unavailable or stale":"No active levels")+". Marker anchors show candle location; text records actual fill price.";
 }
 function syncStudies(rebuild=false){
   if(!chart||!packet)return;
   const key=[...selected].sort().join(",");
   if(rebuild||key!==studyKey){
     for(const x of studySeries)chart.removeSeries(x.series);studySeries=[];studyKey=key;
     let pane=1;
     for(const k of selected){
       const index=lower.has(k)?pane++:0;
       for(const [field,label,color] of defs[k]){
         const options={color,priceLineVisible:false,lastValueVisible:false,title:label};
         const series=chart.addSeries(field==="macd_hist"?L.HistogramSeries:L.LineSeries,field==="macd_hist"?options:{...options,lineWidth:1},index);
         studySeries.push({field,series});
       }
     }
     root.classList.remove("study-count-0","study-count-1","study-count-2","study-count-3");
     root.classList.add("study-count-"+(pane-1));
     id("studyPanels").textContent="";
   }
   const lookup=new Map((packet.studies||[]).map(x=>[x.time,x]));
   for(const {field,series} of studySeries)series.setData(withGaps(packet.candles,packet.step,r=>{const value=lookup.get(r.time)?.[field];return Number.isFinite(value)?{time:r.time,value}:{time:r.time}}));
   readout(crossTime);
 }
 function renderPacket(next,reset){
   if(!ensure())return;
   const time=chart.timeScale(),range=time.getVisibleRange(),follow=reset||!displayed.length||time.scrollPosition()>=-2;
   packet=next;displayed=next.candles;rowsByTime=new Map(displayed.map(r=>[r.time,r]));
   candles.setData(withGaps(displayed,next.step,r=>({time:r.time,open:r.open,high:r.high,low:r.low,close:r.close})));
   volume.setData(withGaps(displayed,next.step,r=>({time:r.time,value:r.volume,color:r.close>=r.open?"#29c99a66":"#f2778366"})));
   syncStudies(reset);
   if(displayed.length&&follow){if(reset){const n=withGaps(displayed,next.step,r=>r).length;time.setVisibleLogicalRange({from:Math.max(0,n-65),to:n+4})}else time.scrollToRealTime()}
   else if(range&&displayed.length)time.setVisibleRange(range);
   overlayView();readout(null);
 }
 function clearSelection(){
   generation++;busy=false;packet=null;displayed=[];rowsByTime.clear();crossTime=null;dispose();id("studyLegend").replaceChildren();id("studyPanels").replaceChildren();id("marketChartTitle").textContent=symbol+" · "+frame;id("marketChartLast").textContent="—";id("marketChartStatus").textContent="Loading chart…";id("chartOverlayNote").textContent="";readout(null);if(visible())load(true);
 }
 async function load(force=false){
   if(!visible()||(!force&&busy))return;
   const g=++generation,s=symbol,f=frame;busy=true;
   try{
     const res=await fetch("/api/chart?symbol="+encodeURIComponent(s)+"&frame="+encodeURIComponent(f),{cache:"no-store"});
     if(!res.ok)throw Error("chart unavailable");
     const p=await res.json();if(g!==generation)return;
     if(p.symbol!==s||p.frame!==f||!Array.isArray(p.candles)||!Number.isFinite(p.step))throw Error("chart identity");
     const reset=!packet;id("marketChartTitle").textContent=s+" · "+f;id("marketChartLast").textContent=p.candles.length?fmt(p.candles.at(-1).close)+" USD":"—";
     const age=p.last_close_age_s,stale=age===null||age>2*p.step||age<0,wide=p.candles.slice(-80).filter(x=>(x.high-x.low)/x.close>.02).length;
     id("marketChartStatus").textContent=p.status==="observed"?(stale?"Stale archive":"Completed archive")+" · "+(p.source==="demo_public_completed_candles"?"Public demo cache":"Trading archive")+" · Last close "+age+"s ago · "+p.gap_count+" gaps · "+p.invalid_rows+" invalid rows · "+wide+" wide-range candles / last "+Math.min(80,p.candles.length):"No chart data available";
     id("marketChartStatus").className=stale||wide?"caution":"";
     renderPacket(p,reset);
   }catch(e){if(g===generation){id("marketChartStatus").textContent="Chart unavailable · retained data may be stale";id("marketChartStatus").className="caution";console.warn("Recover chart:",e.message)}}
   finally{if(g===generation)busy=false}
 }
 function pan(n){if(chart){const scale=chart.timeScale(),r=scale.getVisibleLogicalRange();if(r)scale.setVisibleLogicalRange({from:r.from+n,to:r.to+n});overlayView()}}
 function zoom(factor){if(chart){const scale=chart.timeScale(),r=scale.getVisibleLogicalRange();if(r){const center=(r.from+r.to)/2,half=Math.max(5,Math.min(180,(r.to-r.from)*factor/2));scale.setVisibleLogicalRange({from:center-half,to:center+half})}}}
 function latest(){if(chart){chart.timeScale().scrollToRealTime();overlayView()}load()}
 document.addEventListener("recover:overview",e=>{overlays=new Map(e.detail.map(o=>[o.symbol,o]));if(visible())overlayView()});
 document.addEventListener("recover:market",e=>{if(symbol!==e.detail){symbol=e.detail;clearSelection();dock()}});
 for(const b of document.querySelectorAll("[data-frame]"))b.addEventListener("click",()=>{if(frame===b.dataset.frame)return;frame=b.dataset.frame;for(const a of document.querySelectorAll("[data-frame]"))a.setAttribute("aria-pressed",String(a===b));clearSelection()});
 id("chartZoomIn").addEventListener("click",()=>zoom(.8));id("chartZoomOut").addEventListener("click",()=>zoom(1.25));id("chartLeft").addEventListener("click",()=>pan(-15));id("chartRight").addEventListener("click",()=>pan(15));id("chartReset").addEventListener("click",latest);
 id("chartLevels").addEventListener("click",()=>{levels=!levels;id("chartLevels").setAttribute("aria-pressed",String(levels));overlayView()});id("chartFills").addEventListener("click",()=>{showFills=!showFills;id("chartFills").setAttribute("aria-pressed",String(showFills));overlayView()});
 for(const b of document.querySelectorAll("[data-study]"))b.addEventListener("click",()=>{const k=b.dataset.study;if(selected.has(k))selected.delete(k);else selected.add(k);b.setAttribute("aria-pressed",String(selected.has(k)));id("indicatorCount").textContent=selected.size+" active";syncStudies()});
 function expand(on){id("marketTerminal").classList.toggle("expanded-chart",on);id("marketFullscreen").textContent=on?"Close expanded chart":"Expand chart";id("marketFullscreen").setAttribute("aria-pressed",String(on))}
 id("marketFullscreen").addEventListener("click",()=>expand(!id("marketTerminal").classList.contains("expanded-chart")));
 document.addEventListener("keydown",e=>{if(e.key==="Escape"&&id("marketTerminal").classList.contains("expanded-chart"))expand(false)});
 root.addEventListener("keydown",e=>{if(e.key==="ArrowLeft")pan(-5);else if(e.key==="ArrowRight")pan(5);else if(e.key==="+"||e.key==="=")zoom(.8);else if(e.key==="-")zoom(1.25);else return;e.preventDefault()});
 window.addEventListener("hashchange",()=>{if(visible()){load(true);dock()}else{generation++;busy=false;expand(false)}});
 load();setInterval(load,10000);
})();
