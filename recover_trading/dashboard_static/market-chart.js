"use strict";
(()=>{
 const id=x=>document.getElementById(x),root=id("marketChart"),L=window.LightweightCharts;
 let symbol=document.querySelector("[data-symbol][aria-pressed=true]")?.dataset.symbol||"BTCUSD",frame="5m",packet=null,selected=new Set(),generation=0,busy=false,levels=true,showFills=true,overlays=new Map(),dockKey="",chart=null,candles=null,volume=null,markers=null,priceLines=[],studySeries=[],studyKey="",crossTime=null,displayed=[],rowsByTime=new Map();
 const sourceModes=new Map([["BTCUSD","demo"],["XAUTUSD","reference"]]);
 function sourceMode(){return sourceModes.get(symbol)||"demo"}
 function reference(){return sourceMode()==="reference"}
 const scaleModes=new Map([["BTCUSD","full"],["XAUTUSD","focus"]]);let logarithmic=false,scaleNoteFrame=0;
 let modalInert=[],modalReturnFocus=null;
 let quote=null,quoteLine=null,quoteBusy=false,quoteGeneration=0,quoteReceived=0,quoteFailed=false;
 const colors={up:"#29c99a",down:"#f27783",grid:"#303943",muted:"#a1aebb"};
 const fmt=(n,d=2)=>Number.isFinite(n)?n.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}):"—";
 function visible(){return !root.closest("[data-workspace]").hidden}
 const lineStyle={entry:["ENTRY","#83a9ff"],mark:["MARK","#c4ccd5"],stop:["SL","#f27783"],target:["TP","#29c99a"],break_even:["BE est.","#e6b65c"]};
 const fillNames={entry:"Entry",exit:"Exit",reversal:"Reversal",reduction:"Reduction",increase:"Increase",fill:"Fill"};
 let fillFilter="all",selectedFillId=null,selectedFillLine=null,fillListKey="";
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
 const studyNames={ema9:"EMA 9",ema20:"EMA 20",ema50:"EMA 50",ema200:"EMA 200",bb:"Bollinger Bands",vwap:"UTC VWAP",sr:"Prior support/resistance",rsi:"RSI 14",macd:"MACD 12/26/9",atr:"ATR 14"};
 const presets={trend:["ema20","ema50","ema200"],momentum:["rsi","macd"],volatility:["bb","atr"]};
 const colorClass={"#83a9ff":"study-blue","#e6b65c":"study-amber","#b79af6":"study-purple","#ef9e70":"study-orange","#779bc9":"study-steel","#39cdb7":"study-teal","#29c99a":"study-green","#f27783":"study-red"};
 let studyLookup=new Map();

 function readout(t){
   const row=t===null||t===undefined?packet?.candles?.at(-1):rowsByTime.get(t),s=studyLookup.get(row?.time);
   id("chartReadout").textContent=row?new Date(row.time*1000).toLocaleString()+" · O "+fmt(row.open)+" · H "+fmt(row.high)+" · L "+fmt(row.low)+" · C "+fmt(row.close)+" · V "+fmt(row.volume,0):t!=null?"No observed candle at crosshair":"Open · High · Low · Close · Volume";
   const make=(tag,cls,label)=>{const n=document.createElement(tag);n.className=cls;if(label!=null)n.textContent=label;return n};
   const groups=[...selected].map(k=>{
     const group=make("div","study-value-group");
     group.append(make("strong","study-value-title",studyNames[k]),make("small","study-value-location",lower.has(k)?"Pane":"Overlay"));
     for(const [field,label,color] of defs[k]){
       const n=make("span","study-value "+(colorClass[color]||""));
       n.append(make("i","study-swatch"),make("span","study-value-label",label),make("b","study-value-number",fmt(s?.[field])));
       group.append(n);
     }
     if(!defs[k].some(([field])=>Number.isFinite(s?.[field])))group.append(make("small","study-value-unavailable",row?"Insufficient contiguous history":"No observed candle"));
     return group;
   });
   id("studyLegend").replaceChildren(...groups);
 }
 function scaleKey(){return symbol+(reference()?":reference":"")}
 function scaleMode(){return scaleModes.get(scaleKey())||"full"}
 function visibleBars(){
   const range=chart?.timeScale().getVisibleRange();
   if(range&&typeof range.from==="number"&&typeof range.to==="number"){
     const rows=displayed.filter(r=>r.time>=range.from&&r.time<=range.to);
     if(rows.length)return rows;
   }
   return displayed.slice(-65);
 }
 function bodyBounds(rows){
   if(!rows.length)return null;
   const lo=Math.min(...rows.map(r=>Math.min(r.open,r.close))),hi=Math.max(...rows.map(r=>Math.max(r.open,r.close)));
   if(!Number.isFinite(lo)||!Number.isFinite(hi)||lo<=0)return null;
   const pad=Math.max((hi-lo)*.08,(hi+lo)*.00075);
   return {minValue:Math.max(lo*.001,lo-pad),maxValue:hi+pad};
 }
 function focusAutoscale(base){
   const original=base();
   if(scaleMode()!=="focus")return original;
   const priceRange=bodyBounds(visibleBars());
   return priceRange?{...(original||{}),priceRange}:original;
 }
 function scaleNote(){
   const focused=scaleMode()==="focus",rows=visibleBars(),bounds=bodyBounds(rows);
   id("scaleFull").setAttribute("aria-pressed",String(!focused));
   id("scaleFocus").setAttribute("aria-pressed",String(focused));
   id("scaleLog").setAttribute("aria-pressed",String(logarithmic));
   const outside=bounds?rows.filter(r=>r.low<bounds.minValue||r.high>bounds.maxValue).length:0;
   const wide=rows.filter(r=>(r.high-r.low)/r.close>.02).length;
   id("chartScaleNote").textContent=(focused?"Body focus · wicks and price overlays may extend outside view; raw OHLC unchanged. "+outside+" of "+rows.length+" visible candles have wicks outside body-fit bounds.":"Full range · recorded highs and lows included in autoscale.")+(rows.length?" "+wide+" of "+rows.length+" visible candles have >2% high-low range.":"")+(logarithmic?" Logarithmic axis.":"");
   id("chartScaleNote").classList.toggle("caution",focused||wide>0);
 }
 function scheduleScaleNote(){
   if(scaleNoteFrame)return;
   scaleNoteFrame=requestAnimationFrame(()=>{scaleNoteFrame=0;scaleNote()});
 }
 function applyScale(){
   if(chart&&candles){
     candles.applyOptions({autoscaleInfoProvider:focusAutoscale});
     for(const x of studySeries)if(x.upper)x.series.applyOptions({autoscaleInfoProvider:base=>scaleMode()==="focus"?null:base()});
     chart.priceScale("right").applyOptions({autoScale:true,mode:logarithmic?L.PriceScaleMode.Logarithmic:L.PriceScaleMode.Normal});
   }
   scaleNote();
 }
 function dispose(){selectedFillLine=null;fillListKey="";if(scaleNoteFrame)cancelAnimationFrame(scaleNoteFrame);scaleNoteFrame=0;quoteLine=null;if(chart)chart.remove();chart=null;candles=null;volume=null;markers=null;priceLines=[];studySeries=[];studyKey="";root.replaceChildren();}
 function ensure(){
   if(chart)return true;
   if(!L?.createChart||!L.CandlestickSeries){id("marketChartStatus").textContent="Chart library unavailable · deployment asset missing";return false}
   chart=L.createChart(root,{autoSize:true,localization:{locale:"en-US"},layout:{background:{type:L.ColorType.Solid,color:"#141a22"},textColor:colors.muted,attributionLogo:true,panes:{separatorColor:"#303943",separatorHoverColor:"#49586a",enableResize:true}},grid:{vertLines:{color:colors.grid},horzLines:{color:colors.grid}},rightPriceScale:{borderColor:colors.grid,minimumWidth:74,scaleMargins:{top:.12,bottom:.24}},timeScale:{borderColor:colors.grid,timeVisible:true,secondsVisible:false,rightOffset:5,barSpacing:7,minBarSpacing:1},crosshair:{mode:L.CrosshairMode.Normal},handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},handleScale:{axisPressedMouseMove:true,mouseWheel:true,pinch:true}});
   candles=chart.addSeries(L.CandlestickSeries,{upColor:colors.up,downColor:colors.down,wickUpColor:colors.up,wickDownColor:colors.down,borderVisible:false,priceLineVisible:false,lastValueVisible:true,autoscaleInfoProvider:focusAutoscale});
   volume=chart.addSeries(L.HistogramSeries,{priceScaleId:"volume",priceFormat:{type:"volume"},lastValueVisible:false,priceLineVisible:false});
   volume.priceScale().applyOptions({scaleMargins:{top:.83,bottom:0}});
   markers=L.createSeriesMarkers(candles,[]);
   chart.subscribeCrosshairMove(p=>{crossTime=typeof p.time==="number"?p.time:null;readout(crossTime)});
   chart.timeScale().subscribeVisibleLogicalRangeChange(scheduleScaleNote);
   chart.priceScale("right").applyOptions({mode:logarithmic?L.PriceScaleMode.Logarithmic:L.PriceScaleMode.Normal});
   return true;
 }
 function withGaps(rows,step,map){
   const result=[];let previous=null;
   for(const row of rows){if(previous!==null&&row.time>previous+step)result.push({time:previous+step});result.push(map(row));previous=row.time}
   return result;
 }
 function sourceView(){
   id("chartSourceLabel").textContent=reference()?"PRODUCTION MARKET REFERENCE · ANALYSIS ONLY":"DEMO EXECUTION MARKET · COMPLETED CANDLES";
   id("chartReference").setAttribute("aria-pressed",String(reference()));id("chartDemo").setAttribute("aria-pressed",String(!reference()));
   for(const name of ["chartLevels","chartFills","chartFillFilter"])id(name).disabled=reference();
   id("chartExecutions").hidden=reference();id("clearFillSelection").disabled=reference()||!selectedFillId;
 }
 function quoteView(){
   const q=quote,age=q&&Number.isFinite(q.age_s)?q.age_s+Math.max(0,(performance.now()-quoteReceived)/1000):null;
   const current=q?.symbol===symbol&&q.status==="observed"&&age!==null&&age>=-2&&age<=15&&!quoteFailed;
   id("chartLivePrice").textContent=q?.symbol===symbol&&Number.isFinite(q.last_price)?fmt(q.last_price)+" USD":"—";
   id("chartLiveMark").textContent=q?.symbol===symbol&&Number.isFinite(q.mark_price)?"Mark "+fmt(q.mark_price):"Mark —";
   id("chartLiveState").textContent=current?(reference()?"Reference":"Public demo")+" last price · "+Math.max(0,Math.round(age))+"s old":q?.last_price!=null?"Last observed quote · stale / disconnected":(reference()?"Reference":"Public demo")+" last price · unavailable";
   id("quoteDot").classList.toggle("quote-active",Boolean(current));
   if(quoteLine&&candles){candles.removePriceLine(quoteLine);quoteLine=null}
   if(current&&candles&&packet&&chart.timeScale().scrollPosition()>=-2){
     quoteLine=candles.createPriceLine({price:q.last_price,color:"#53d6ae",lineWidth:1,lineStyle:L.LineStyle.Dotted,axisLabelVisible:true,title:"LAST"});
   }
 }
 async function loadQuote(){
   if(!visible()||quoteBusy)return;
   quoteBusy=true;const g=++quoteGeneration,s=symbol,source=sourceMode();
   try{
     const response=await fetch("/api/chart-quote?symbol="+encodeURIComponent(s)+"&source="+source,{cache:"no-store"});
     if(!response.ok)throw Error("quote unavailable");
     const p=await response.json();if(g!==quoteGeneration||symbol!==s)return;
     if(p.symbol!==s||p.source!==(source==="reference"?"reference_public_ticker":"demo_public_ticker"))throw Error("quote identity");
     quote=p;quoteReceived=performance.now();quoteFailed=false;quoteView();
   }catch(e){if(g===quoteGeneration){quoteFailed=true;quoteView()}}
   finally{if(g===quoteGeneration)quoteBusy=false}
 }
 function knownFills(){
   return (reference()?[]:overlay().fills||[]).filter(f=>typeof f.id==="string"&&Number.isFinite(f.time)&&Number.isFinite(f.price)&&f.price>0&&["buy","sell"].includes(f.side));
 }
 function candleTime(f){return packet?Math.floor(f.time/packet.step)*packet.step:null}
 function matchingFills(){return knownFills().filter(f=>fillFilter==="all"||f.kind===fillFilter||(fillFilter==="adjustment"&&["increase","reduction"].includes(f.kind)))}
 function fillTimeLabel(f){return new Date(f.time*1000).toLocaleString()}
 function renderFillSelection(){
   if(selectedFillLine&&candles)candles.removePriceLine(selectedFillLine);
   selectedFillLine=null;
   const f=knownFills().find(x=>x.id===selectedFillId);
   id("clearFillSelection").disabled=!selectedFillId;
   id("chartFillDetail").textContent=f?fillNames[f.kind]+" · "+f.side.toUpperCase()+" · "+f.size+" contracts · actual fill "+fmt(f.price)+" USD · "+fillTimeLabel(f)+(rowsByTime.has(candleTime(f))?" · candle located in archive":" · no completed candle in loaded window"):"Select a recorded fill to locate its candle and actual execution price.";
   if(f&&candles&&rowsByTime.has(candleTime(f)))selectedFillLine=candles.createPriceLine({price:f.price,color:"#e6b65c",lineWidth:2,lineStyle:L.LineStyle.Dotted,axisLabelVisible:true,title:"SELECTED FILL"});
 }
 function jumpToFill(f){
   selectedFillId=f.id;fillListKey="";renderFillSelection();
   if(chart&&rowsByTime.has(candleTime(f))){
     const t=candleTime(f),index=withGaps(displayed,packet.step,r=>r).findIndex(r=>r.time===t);
     if(index>=0){chart.timeScale().setVisibleLogicalRange({from:Math.max(0,index-25),to:index+25});readout(t)}
   }
   overlayView();
 }
 function fillListView(){
   const all=knownFills(),fills=matchingFills(),loaded=fills.filter(f=>rowsByTime.has(candleTime(f)));
   id("chartFillCount").textContent=loaded.length+" / "+all.length+" fills";
   const key=JSON.stringify([symbol,frame,fillFilter,selectedFillId,fills.map(f=>[f.id,f.time,f.price,f.size,f.kind,f.side,rowsByTime.has(candleTime(f))])]);
   if(key!==fillListKey){
     fillListKey=key;const wrap=id("chartFillList");wrap.replaceChildren();
     if(!fills.length){const p=document.createElement("p");p.className="empty";p.textContent="No recorded fills for this filter.";wrap.append(p)}
     for(const f of fills.slice().sort((a,b)=>b.time-a.time).slice(0,100)){
       const b=document.createElement("button");b.className="chart-fill-row";b.type="button";b.setAttribute("aria-pressed",String(f.id===selectedFillId));
       const make=(tag,cls,label)=>{const n=document.createElement(tag);n.className=cls;n.textContent=label;return n};
       b.append(make("strong","fill-kind "+(f.side==="buy"?"gain":"loss"),(fillNames[f.kind]||"Fill")+" · "+f.side.toUpperCase()),make("strong","fill-price",fmt(f.price)),make("small","fill-stamp",fillTimeLabel(f)),make("small","fill-size",f.size+" contracts"),make("small","fill-coverage",rowsByTime.has(candleTime(f))?"Locate candle":"Outside loaded completed candles"));
       b.addEventListener("click",()=>jumpToFill(f));wrap.append(b);
     }
   }
   renderFillSelection();
 }
 function overlayView(){
   dock();quoteView();fillListView();sourceView();if(!chart||!packet)return;
   for(const line of priceLines)candles.removePriceLine(line);priceLines=[];
   if(reference()){markers.setMarkers([]);id("chartOverlayNote").textContent="Reference prices only · demo execution markers and position levels are hidden. Switch to Demo execution to inspect fills.";return}
   const o=overlay(),fresh=isFresh(o),live=levels&&fresh&&o.status==="position_observed";
   const atLatest=chart.timeScale().scrollPosition()>=-2;
   if(live&&atLatest)for(const l of o.lines||[]){if(!lineStyle[l.kind]||!Number.isFinite(l.price)||l.price<=0)continue;const [title,color]=lineStyle[l.kind];priceLines.push(candles.createPriceLine({price:l.price,color,lineWidth:l.kind==="entry"?2:1,lineStyle:l.kind==="entry"?L.LineStyle.Solid:l.kind==="mark"?L.LineStyle.Dotted:L.LineStyle.Dashed,axisLabelVisible:true,title}));}
   const fills=showFills?matchingFills().filter(f=>rowsByTime.has(candleTime(f))):[];
   // Compact markers identify observed action; exact price is shown in the selected-fill line and list.
   markers.setMarkers(fills.map(f=>({id:f.id,time:candleTime(f),position:f.side==="buy"?"belowBar":"aboveBar",color:f.id===selectedFillId?"#e6b65c":f.kind==="exit"?"#b79af6":f.kind==="reversal"?"#e6b65c":f.side==="buy"?colors.up:colors.down,shape:f.kind==="exit"?"circle":f.kind==="reversal"?"square":f.side==="buy"?"arrowUp":"arrowDown",text:({entry:"E",exit:"X",reversal:"R",increase:"+",reduction:"−"})[f.kind]||"F"})).sort((a,b)=>a.time-b.time));
   id("chartOverlayNote").textContent=fills.length+" displayed fills in loaded archive · "+(live&&atLatest?"Current snapshot price lines, not historical levels":!atLatest?"Current levels hidden while panning":!fresh?"Position snapshot unavailable or stale":!levels?"Position levels hidden":"No active levels")+". E entry · X exit · R reversal · + increase · − reduction · F fill. Marker anchors identify the candle; select a fill for its actual price.";

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
         const options={color,priceLineVisible:false,lastValueVisible:false,title:label,...(index===0?{autoscaleInfoProvider:base=>scaleMode()==="focus"?null:base()}: {})};
         if(field==="rsi")options.autoscaleInfoProvider=()=>({priceRange:{minValue:0,maxValue:100}});
         const series=chart.addSeries(field==="macd_hist"?L.HistogramSeries:L.LineSeries,field==="macd_hist"?{...options,base:0}:{...options,lineWidth:2},index);
         if(field==="rsi")for(const level of [30,70])series.createPriceLine({price:level,color:"#8493a5",lineWidth:1,lineStyle:L.LineStyle.Dashed,axisLabelVisible:true,title:"RSI "+level});
         if(field==="macd_hist")series.createPriceLine({price:0,color:"#8493a5",lineWidth:1,lineStyle:L.LineStyle.Dotted,axisLabelVisible:false,title:"Zero"});
         if(index>0)series.priceScale().applyOptions({scaleMargins:{top:.1,bottom:.1},autoScale:true});
         studySeries.push({field,series,upper:index===0});
       }
     }
     root.classList.remove("study-count-0","study-count-1","study-count-2","study-count-3");
     root.classList.add("study-count-"+(pane-1));
     id("studyPanels").textContent="";
   }
   for(const {field,series} of studySeries)series.setData(withGaps(packet.candles,packet.step,r=>{const value=studyLookup.get(r.time)?.[field];return Number.isFinite(value)?{time:r.time,value,...(field==="macd_hist"?{color:value>=0?"#29c99a":"#f27783"}:{})}:{time:r.time}}));
   readout(crossTime);
 }
 function renderPacket(next,reset){
   if(!ensure())return;
   const time=chart.timeScale(),range=time.getVisibleRange(),follow=reset||!displayed.length||time.scrollPosition()>=-2;
   packet=next;displayed=next.candles;rowsByTime=new Map(displayed.map(r=>[r.time,r]));studyLookup=new Map((next.studies||[]).map(r=>[r.time,r]));
   candles.setData(withGaps(displayed,next.step,r=>({time:r.time,open:r.open,high:r.high,low:r.low,close:r.close})));
   volume.setData(withGaps(displayed,next.step,r=>({time:r.time,value:r.volume,color:r.close>=r.open?"#29c99a66":"#f2778366"})));
   syncStudies(reset);
   if(displayed.length&&follow){if(reset){const n=withGaps(displayed,next.step,r=>r).length;time.setVisibleLogicalRange({from:Math.max(0,n-65),to:n+4})}else time.scrollToRealTime()}
   else if(range&&displayed.length)time.setVisibleRange(range);
   overlayView();readout(null);scheduleScaleNote();
 }
 function clearSelection(){
   generation++;busy=false;packet=null;displayed=[];rowsByTime.clear();studyLookup.clear();crossTime=null;dispose();id("studyLegend").replaceChildren();id("studyPanels").replaceChildren();id("marketChartTitle").textContent=symbol+" · "+frame;id("marketChartLast").textContent="—";id("marketChartStatus").textContent="Loading chart…";id("chartOverlayNote").textContent="";readout(null);scaleNote();fillListView();sourceView();if(visible())load(true);
 }
 async function load(force=false){
   if(!visible()||(!force&&busy))return;
   const g=++generation,s=symbol,f=frame,source=sourceMode();busy=true;
   try{
     const res=await fetch("/api/chart?symbol="+encodeURIComponent(s)+"&frame="+encodeURIComponent(f)+"&source="+source,{cache:"no-store"});
     if(!res.ok)throw Error("chart unavailable");
     const p=await res.json();if(g!==generation)return;
     if(p.symbol!==s||p.frame!==f||!Array.isArray(p.candles)||!Number.isFinite(p.step)||(source==="reference"?p.source!=="reference_public_completed_candles":!["demo_public_completed_candles","demo_archived_completed_candles"].includes(p.source)))throw Error("chart identity");
     const reset=!packet;id("marketChartTitle").textContent=s+" · "+f;id("marketChartLast").textContent=p.candles.length?fmt(p.candles.at(-1).close)+" USD":"—";
     const age=p.last_close_age_s,stale=age===null||age>2*p.step||age<0,wide=p.candles.slice(-80).filter(x=>(x.high-x.low)/x.close>.02).length;
     id("marketChartStatus").textContent=p.status==="observed"?(stale?"Stale archive":"Completed archive")+" · "+(p.source==="reference_public_completed_candles"?"Production reference":p.source==="demo_public_completed_candles"?"Public demo cache":"Trading archive")+" · Last close "+age+"s ago · "+p.gap_count+" gaps · "+p.invalid_rows+" invalid rows · "+wide+" wide-range candles / last "+Math.min(80,p.candles.length):"No chart data available";
     id("marketChartStatus").className=stale||wide?"caution":"";
     renderPacket(p,reset);
   }catch(e){if(g===generation){id("marketChartStatus").textContent="Chart unavailable · retained data may be stale";id("marketChartStatus").className="caution";console.warn("Recover chart:",e.message)}}
   finally{if(g===generation)busy=false}
 }
 function pan(n){if(chart){const scale=chart.timeScale(),r=scale.getVisibleLogicalRange();if(r)scale.setVisibleLogicalRange({from:r.from+n,to:r.to+n});overlayView()}}
 function zoom(factor){if(chart){const scale=chart.timeScale(),r=scale.getVisibleLogicalRange();if(r){const center=(r.from+r.to)/2,half=Math.max(5,Math.min(180,(r.to-r.from)*factor/2));scale.setVisibleLogicalRange({from:center-half,to:center+half})}}}
 function latest(){if(chart){chart.timeScale().scrollToRealTime();overlayView()}load()}
 function selectSource(source){if(sourceMode()===source)return;sourceModes.set(symbol,source);selectedFillId=null;logarithmic=false;quoteGeneration++;quoteBusy=false;quote=null;quoteFailed=false;clearSelection();quoteView();loadQuote()}
 id("chartReference").addEventListener("click",()=>selectSource("reference"));id("chartDemo").addEventListener("click",()=>selectSource("demo"));
 sourceView();
 document.addEventListener("recover:overview",e=>{overlays=new Map(e.detail.map(o=>[o.symbol,o]));if(visible())overlayView()});
 document.addEventListener("recover:market",e=>{for(const b of document.querySelectorAll("[data-chart-symbol]"))b.setAttribute("aria-pressed",String(b.dataset.chartSymbol===e.detail));if(symbol!==e.detail){selectedFillId=null;symbol=e.detail;logarithmic=false;quoteGeneration++;quoteBusy=false;quote=null;quoteFailed=false;clearSelection();quoteView();loadQuote();dock()}});
 for(const b of document.querySelectorAll("[data-frame]"))b.addEventListener("click",()=>{if(frame===b.dataset.frame)return;frame=b.dataset.frame;for(const a of document.querySelectorAll("[data-frame]"))a.setAttribute("aria-pressed",String(a===b));clearSelection()});
 id("chartZoomIn").addEventListener("click",()=>zoom(.8));id("chartZoomOut").addEventListener("click",()=>zoom(1.25));id("chartLeft").addEventListener("click",()=>pan(-15));id("chartRight").addEventListener("click",()=>pan(15));id("chartReset").addEventListener("click",latest);
 id("chartFillFilter").addEventListener("change",e=>{fillFilter=e.target.value;selectedFillId=null;fillListKey="";overlayView()});
 id("clearFillSelection").addEventListener("click",()=>{selectedFillId=null;fillListKey="";overlayView()});
 id("scaleFull").addEventListener("click",()=>{scaleModes.set(scaleKey(),"full");applyScale()});
 id("scaleFocus").addEventListener("click",()=>{scaleModes.set(scaleKey(),"focus");applyScale()});
 id("scaleLog").addEventListener("click",()=>{logarithmic=!logarithmic;applyScale()});
 id("scaleAuto").addEventListener("click",applyScale);
 scaleNote();
 id("chartLevels").addEventListener("click",()=>{levels=!levels;id("chartLevels").setAttribute("aria-pressed",String(levels));overlayView()});id("chartFills").addEventListener("click",()=>{showFills=!showFills;id("chartFills").setAttribute("aria-pressed",String(showFills));overlayView()});
 function updateStudyControls(){for(const b of document.querySelectorAll("[data-study]"))b.setAttribute("aria-pressed",String(selected.has(b.dataset.study)));id("indicatorCount").textContent=selected.size+" active";syncStudies();readout(crossTime)}
 function selectPreset(keys){selected=new Set(keys);updateStudyControls()}
 id("studyTrend").addEventListener("click",()=>selectPreset(presets.trend));id("studyMomentum").addEventListener("click",()=>selectPreset(presets.momentum));id("studyVolatility").addEventListener("click",()=>selectPreset(presets.volatility));id("studyClear").addEventListener("click",()=>selectPreset([]));
 for(const b of document.querySelectorAll("[data-study]"))b.addEventListener("click",()=>{const k=b.dataset.study;if(selected.has(k))selected.delete(k);else selected.add(k);updateStudyControls()});
 function fullscreenTools(on){
   id("marketTerminal").classList.toggle("expanded-price-tools",on);
   id("fullscreenTools").setAttribute("aria-expanded",String(on));
 }
 function expand(on){
   const terminal=id("marketTerminal"),toggle=id("marketFullscreen");
   if(terminal.classList.contains("expanded-chart")===on)return;
   if(on){
     modalReturnFocus=document.activeElement;
     terminal.classList.add("expanded-chart");document.body.classList.add("chart-modal-open");
     terminal.setAttribute("role","dialog");terminal.setAttribute("aria-modal","true");
     id("fullscreenToolbar").hidden=false;
     fullscreenTools(false);
     for(const d of terminal.querySelectorAll("details"))d.open=false;
     // Inert siblings along the ancestor chain, never the actual chart or its ancestors.
     modalInert=[];
     for(let n=terminal;n&&n!==document.body;n=n.parentElement){
       for(const other of n.parentElement.children){
         if(other===n||other.inert||["SCRIPT","STYLE","LINK"].includes(other.tagName))continue;
         other.inert=true;modalInert.push(other);
       }
     }
     terminal.scrollTop=0;toggle.textContent="Close chart";toggle.setAttribute("aria-pressed","true");
     toggle.focus({preventScroll:true});
   }else{
     terminal.classList.remove("expanded-chart","expanded-price-tools");document.body.classList.remove("chart-modal-open");
     terminal.removeAttribute("role");terminal.removeAttribute("aria-modal");id("fullscreenToolbar").hidden=true;
     for(const other of modalInert)other.inert=false;
     modalInert=[];toggle.textContent="Expand chart";toggle.setAttribute("aria-pressed","false");fullscreenTools(false);
     if(visible()&&modalReturnFocus?.isConnected)modalReturnFocus.focus({preventScroll:true});
     modalReturnFocus=null;
   }
 }
 id("marketFullscreen").addEventListener("click",()=>expand(!id("marketTerminal").classList.contains("expanded-chart")));
 id("fullscreenTools").addEventListener("click",()=>fullscreenTools(id("fullscreenTools").getAttribute("aria-expanded")!=="true"));
 for(const b of document.querySelectorAll("[data-chart-symbol]"))b.addEventListener("click",()=>document.dispatchEvent(new CustomEvent("recover:select-market",{detail:b.dataset.chartSymbol})));
 document.addEventListener("keydown",e=>{
   const terminal=id("marketTerminal");if(!terminal.classList.contains("expanded-chart"))return;
   if(e.key==="Escape"){e.preventDefault();expand(false);return}
   if(e.key!=="Tab")return;
   const focusable=[...terminal.querySelectorAll("button:not([disabled]),select:not([disabled]),summary,a[href],[tabindex='0']")].filter(n=>n.getClientRects().length>0);
   if(!focusable.length)return;
   const first=focusable[0],last=focusable.at(-1);
   if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}
   else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
 });
 root.addEventListener("keydown",e=>{if(e.key==="ArrowLeft")pan(-5);else if(e.key==="ArrowRight")pan(5);else if(e.key==="+"||e.key==="=")zoom(.8);else if(e.key==="-")zoom(1.25);else return;e.preventDefault()});
 window.addEventListener("hashchange",()=>{if(visible()){load(true);loadQuote();dock()}else{generation++;busy=false;quoteGeneration++;quoteBusy=false;expand(false)}});
 load();loadQuote();setInterval(load,10000);setInterval(loadQuote,3000);
})();
