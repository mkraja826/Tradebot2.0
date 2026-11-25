"use strict";
(()=>{
 const id=x=>document.getElementById(x),root=id("marketChart"),ns="http://www.w3.org/2000/svg";
 let symbol=document.querySelector("[data-symbol][aria-pressed=true]")?.dataset.symbol||"BTCUSD",frame="5m",packet=null,windowSize=80,offset=0,ema=false,generation=0,busy=false,drag=null,hover=null,levels=true,showFills=true,overlays=new Map(),dockKey="";
 const colors={up:"#29c99a",down:"#f27783",grid:"#303943",muted:"#a1aebb",ema:"#e6b65c"};
 const fmt=(n,d=2)=>Number.isFinite(n)?n.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}):"—";
 const node=(tag,attrs={},text)=>{const el=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));if(text!==undefined)el.textContent=text;return el};
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
 function view(){
   dock();
   if(!packet?.candles?.length){root.replaceChildren();return}
   const all=packet.candles,step=packet.step,last=all.at(-1).time,finish=last-offset*step,start=finish-(windowSize-1)*step;
   const rows=all.filter(r=>r.time>=start&&r.time<=finish);
   if(!rows.length){root.replaceChildren();return}
   const W=Math.max(300,root.clientWidth||600),H=Math.max(270,root.clientHeight||400),left=10,right=W-108,top=12,bottom=H-77,volTop=H-59,volBottom=H-28;
   const o=overlay(),liveLines=levels&&offset===0&&isFresh(o)&&o.status==="position_observed"?(o.lines||[]).filter(l=>lineStyle[l.kind]&&Number.isFinite(l.price)&&l.price>0):[];
   const times=new Set(rows.map(r=>r.time)),fills=showFills?(o.fills||[]).filter(f=>Number.isFinite(f.price)&&f.price>0&&times.has(Math.floor(f.time/step)*step)):[];
   const prices=[...liveLines.map(l=>l.price),...fills.map(f=>f.price)];
   const high=Math.max(...rows.map(r=>r.high),...prices),low=Math.min(...rows.map(r=>r.low),...prices),pad=(high-low||high*.001)*.07,lo=low-pad,hi=high+pad;
   id("chartOverlayNote").textContent=fills.length+" recorded fills in visible completed candles · "+(liveLines.length?"Current snapshot levels (not historical levels)":offset!==0?"Current levels hidden while panning history":!isFresh(o)?"Position snapshot unavailable or stale":"No active levels")+" · Fill markers may include earlier account trades.";
   const dx=(right-left)/windowSize,X=t=>left+((t-start)/step+.5)*dx,Y=p=>top+(hi-p)/(hi-lo)*(bottom-top);
   const svg=node("svg",{viewBox:"0 0 "+W+" "+H,width:W,height:H,role:"img","aria-label":symbol+" "+frame+" completed candlesticks"});
   const add=(tag,attrs,text)=>{const n=node(tag,attrs,text);svg.append(n);return n};
   for(let i=0;i<=5;i++){let p=lo+(hi-lo)*i/5,y=Y(p);add("line",{x1:left,x2:right,y1:y,y2:y,stroke:colors.grid,"stroke-width":.7});add("text",{x:right+6,y:y+4,fill:colors.muted,"font-size":11},fmt(p))}
   const maxVol=Math.max(1,...rows.map(r=>r.volume));
   for(const r of rows){
     const x=X(r.time),c=r.close>=r.open?colors.up:colors.down,w=Math.max(1,dx*.68);
     add("line",{x1:x,x2:x,y1:Y(r.high),y2:Y(r.low),stroke:c,"stroke-width":1});
     add("rect",{x:x-w/2,y:Math.min(Y(r.open),Y(r.close)),width:w,height:Math.max(1,Math.abs(Y(r.open)-Y(r.close))),fill:c,rx:.5});
     const v=(volBottom-volTop)*r.volume/maxVol;add("rect",{x:x-w/2,y:volBottom-v,width:w,height:v,fill:c,opacity:.48});
   }
   if(ema){let e=null,prev=null,segment=[];const draw=()=>{if(segment.length>1)add("polyline",{points:segment.join(" "),stroke:colors.ema,"stroke-width":1.4,fill:"none"});segment=[]};
     for(const r of all){if(prev!==null&&r.time-prev!==step){e=null;draw()}e=e===null?r.close:e+(r.close-e)*2/21;if(r.time>=start&&r.time<=finish)segment.push(X(r.time)+","+Y(e));prev=r.time}draw()}
   for(let i=0;i<4;i++){const t=start+Math.round((windowSize-1)*i/3)*step,x=X(t);add("line",{x1:x,x2:x,y1:top,y2:volBottom,stroke:colors.grid,"stroke-width":.6});const date=new Date(t*1000);add("text",{x:Math.min(right-22,Math.max(33,x)),y:H-9,fill:colors.muted,"font-size":10,"text-anchor":"middle"},step>=3600?date.toLocaleDateString(undefined,{month:"short",day:"numeric"}):date.toLocaleTimeString(undefined,{hour:"2-digit",minute:"2-digit"}))}
   // All prices are actual recorded values; labels are staggered without moving the lines.
   const positioned=liveLines.map(l=>({...l,y:Y(l.price)})).sort((a,b)=>a.y-b.y);let prev=top-15;
   for(const l of positioned){l.labelY=Math.max(l.y,prev+15);prev=l.labelY}
   if(positioned.length&&prev>bottom){const delta=prev-bottom;for(const l of positioned)l.labelY-=delta}
   for(const l of positioned){const [label,c]=lineStyle[l.kind];add("line",{x1:left,x2:right,y1:l.y,y2:l.y,stroke:c,"stroke-dasharray":l.kind==="mark"?"2 3":"6 4","stroke-width":1});add("line",{x1:right,x2:right+5,y1:l.y,y2:l.labelY,stroke:c});add("rect",{x:right+5,y:l.labelY-7,width:101,height:14,rx:2,fill:"#202833",stroke:c,"stroke-width":.5});add("text",{x:right+9,y:l.labelY+3,fill:c,"font-size":9},label+" "+fmt(l.price,2))}
   for(const f of fills){const x=X(Math.floor(f.time/step)*step),y=Y(f.price),c=f.side==="buy"?colors.up:colors.down;
     const dot=add("circle",{cx:x,cy:y,r:4.2,fill:c,stroke:"#141a22","stroke-width":1.3});dot.append(node("title",{},f.kind+" · "+f.side+" "+f.size+" @ "+fmt(f.price)+" · "+new Date(f.time*1000).toLocaleString()));
     if(f.kind==="entry"||f.kind==="exit")add("text",{x:x+6,y:y-6,fill:c,"font-size":10,"font-weight":700},f.kind==="entry"?"E":"X");
   }
   const r=hover===null?rows.at(-1):rows.reduce((a,b)=>Math.abs(b.time-hover)<Math.abs(a.time-hover)?b:a);
   id("chartReadout").textContent=new Date(r.time*1000).toLocaleString()+" · O "+fmt(r.open)+" · H "+fmt(r.high)+" · L "+fmt(r.low)+" · C "+fmt(r.close)+" · V "+fmt(r.volume,0);
   if(hover!==null){const x=X(r.time);add("line",{x1:x,x2:x,y1:top,y2:volBottom,stroke:"#91a1b6","stroke-dasharray":"4 4"});add("line",{x1:left,x2:right,y1:Y(r.close),y2:Y(r.close),stroke:"#91a1b6","stroke-dasharray":"4 4"})}
   root.replaceChildren(svg);
 }
 function limit(){const rows=packet?.candles||[];return rows.length?Math.max(0,Math.round((rows.at(-1).time-rows[0].time)/packet.step)+1-windowSize):0}
 function pan(n){offset=Math.max(0,Math.min(limit(),offset+n));hover=null;view()}
 function zoom(n){windowSize=Math.max(15,Math.min(300,Math.round(windowSize*n)));offset=Math.min(offset,limit());hover=null;view()}
 async function load(force=false){
   if(!visible()||(!force&&busy))return;
   const g=++generation,s=symbol,f=frame;busy=true;
   try{
     const res=await fetch("/api/chart?symbol="+encodeURIComponent(s)+"&frame="+encodeURIComponent(f),{cache:"no-store"});
     if(!res.ok)throw Error("chart unavailable");
     const p=await res.json();if(g!==generation)return;
     if(p.symbol!==s||p.frame!==f||!Array.isArray(p.candles))throw Error("chart identity");
     packet=p;offset=Math.min(offset,limit());id("marketChartTitle").textContent=s+" · "+f;
     id("marketChartLast").textContent=fmt(p.candles.at(-1)?.close)+" USD";
     const age=p.last_close_age_s, stale=age===null||age>2*p.step;
     id("marketChartStatus").textContent=p.status==="observed"?(stale?"Stale archive":"Completed archive")+" · Last close "+age+"s ago · "+p.gap_count+" gaps · "+p.invalid_rows+" invalid rows": "No chart data available";
     id("marketChartStatus").className=stale?"caution":"";
     view();
   }catch(e){if(g===generation){id("marketChartStatus").textContent="Chart connection unavailable · retained data may be stale";id("marketChartStatus").className="caution"}}
   finally{if(g===generation)busy=false}
 }
 function resetSelection(){generation++;busy=false;packet=null;offset=0;hover=null;root.replaceChildren();id("marketChartTitle").textContent=symbol+" · "+frame;id("marketChartLast").textContent="—";id("marketChartStatus").textContent="Loading chart…";id("chartOverlayNote").textContent="";load(true)}
 document.addEventListener("recover:overview",e=>{overlays=new Map(e.detail.map(o=>[o.symbol,o]));if(visible())view()});
 document.addEventListener("recover:market",e=>{if(symbol!==e.detail){symbol=e.detail;resetSelection();dock()}});
 for(const b of document.querySelectorAll("[data-frame]"))b.addEventListener("click",()=>{frame=b.dataset.frame;for(const a of document.querySelectorAll("[data-frame]"))a.setAttribute("aria-pressed",String(a===b));resetSelection()});
 id("chartZoomIn").addEventListener("click",()=>zoom(.8));id("chartZoomOut").addEventListener("click",()=>zoom(1.25));
 id("chartLeft").addEventListener("click",()=>pan(Math.ceil(windowSize/4)));id("chartRight").addEventListener("click",()=>pan(-Math.ceil(windowSize/4)));id("chartReset").addEventListener("click",()=>{offset=0;windowSize=80;hover=null;view();load()});
 id("chartLevels").addEventListener("click",()=>{levels=!levels;id("chartLevels").setAttribute("aria-pressed",String(levels));view()});
 id("chartFills").addEventListener("click",()=>{showFills=!showFills;id("chartFills").setAttribute("aria-pressed",String(showFills));view()});
 id("chartEma").addEventListener("click",()=>{ema=!ema;id("chartEma").setAttribute("aria-pressed",String(ema));view()});
 id("marketFullscreen").addEventListener("click",()=>{const on=id("marketTerminal").classList.toggle("expanded-chart");id("marketFullscreen").textContent=on?"Close expanded chart":"Expand chart";view()});
 document.addEventListener("keydown",e=>{if(e.key==="Escape"&&id("marketTerminal").classList.contains("expanded-chart")){id("marketTerminal").classList.remove("expanded-chart");id("marketFullscreen").textContent="Expand chart";view()}});
 root.addEventListener("keydown",e=>{if(e.key==="ArrowLeft"){pan(5)}else if(e.key==="ArrowRight"){pan(-5)}else if(e.key==="+"||e.key==="="){zoom(.8)}else if(e.key==="-"){zoom(1.25)}else return;e.preventDefault()});
 root.addEventListener("wheel",e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();zoom(e.deltaY>0?1.15:.87)},{passive:false});
 root.addEventListener("pointerdown",e=>{if(!packet?.candles.length)return;drag={x:e.clientX,offset};root.setPointerCapture(e.pointerId)});
 root.addEventListener("pointermove",e=>{if(!packet?.candles.length)return;const rect=root.getBoundingClientRect();if(drag){offset=Math.max(0,Math.min(limit(),drag.offset+Math.round((e.clientX-drag.x)*windowSize/Math.max(1,rect.width-118))));hover=null}else{const last=packet.candles.at(-1).time-offset*packet.step;hover=last-(windowSize-1)*packet.step+Math.round((e.clientX-rect.left-10)*windowSize/Math.max(1,rect.width-118))*packet.step}view()});
 for(const event of ["pointerup","pointercancel","lostpointercapture"])root.addEventListener(event,()=>{drag=null});
 root.addEventListener("pointerleave",()=>{if(!drag){hover=null;view()}});
 window.addEventListener("hashchange",()=>{if(visible()){view();load(true)}else{generation++;busy=false;id("marketTerminal").classList.remove("expanded-chart");id("marketFullscreen").textContent="Expand chart"}});
 new ResizeObserver(()=>{if(visible())view()}).observe(root);
 load();setInterval(load,10000);
})();