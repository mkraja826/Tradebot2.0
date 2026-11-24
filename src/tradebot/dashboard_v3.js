document.getElementById('notice').textContent='Connecting to dashboard data…';

const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
const fmt=v=>v===null||v===undefined?'Unknown':typeof v==='boolean'?(v?'Yes':'No'):String(v);
function row(p,k,v){const n=el('div',undefined,'row');n.append(el('span',k),el('span',fmt(v)));p.append(n)}
function section(p,title){p.append(el('h3',title))}
const pages=new Map();
function paged(key,items,parent,redraw,defaultSize=10){
 const state=pages.get(key)||{page:0,size:defaultSize};pages.set(key,state);
 const total=items.length,max=Math.max(0,Math.ceil(total/state.size)-1);state.page=Math.min(max,Math.max(0,state.page));
 if(total<=defaultSize&&state.size===defaultSize)return items;
 const nav=el('div',undefined,'pager'),prev=el('button','‹ Prev'),next=el('button','Next ›'),size=el('select');
 prev.type=next.type='button';prev.disabled=state.page===0;next.disabled=state.page===max;
 prev.onclick=()=>{state.page--;redraw()};next.onclick=()=>{state.page++;redraw()};
 for(const n of [5,10,20,50]){const o=el('option',n+' / page');o.value=n;size.append(o)}size.value=String(state.size);size.setAttribute('aria-label','Rows per page');size.onchange=()=>{state.size=Number(size.value);state.page=0;redraw()};
 const start=state.page*state.size,end=Math.min(total,start+state.size);
 nav.append(prev,el('small',total?(start+1)+'–'+end+' of '+total:'0 records'),next,size);
 parent.append(nav);return items.slice(start,end);
}
function resetPages(prefix){for(const [key,state] of pages)if(key.startsWith(prefix))state.page=0}
function render(d){const health=document.getElementById('health'),markets=document.getElementById('markets');health.replaceChildren();markets.replaceChildren();
for(const [name,x] of Object.entries(d.sources)){const n=el('div',undefined,'tile');n.append(el('span',name),el('strong',x.state,x.state),el('span',x.age_seconds===null?'No report':x.age_seconds+'s old','sub'));health.append(n)}
for(const [s,m] of Object.entries(d.markets)){const p=el('article',undefined,'panel');p.append(el('h2',s+' / '+m.model_route));section(p,'Market data · '+d.sources.collector.state);row(p,'Feeds ready',Object.values(m.feeds).filter(x=>['ready','cached_current'].includes(x)).length+' / '+Object.keys(m.feeds).length);section(p,'Scanner · '+d.sources.scanner.state);row(p,'Status',m.scanner.status);row(p,'Journal events',m.journal.events);row(p,'Journal signals',m.journal.signals);const sigs=m.scanner.signals||[],sigList=el('div');p.append(sigList);for(const a of paged('signal:'+s,sigs,p,()=>display(lastData),5))row(sigList,a.id+' · '+a.frame,a.direction);section(p,'Position · '+d.sources.position.state);row(p,'State',m.position.status);row(p,'Open orders',m.position.open_order_count);const positions=el('div');p.append(positions);for(const a of paged('overview-position:'+s,m.position.positions||[],p,()=>display(lastData),5))row(positions,a.side+' · '+a.quantity+' contracts',a.protection);section(p,'Learning · '+d.sources.learning.state);row(p,'Observed / pending',fmt(m.learning.observed)+' / '+fmt(m.learning.pending));row(p,'Missing windows',m.learning.missing);row(p,'Trade outcome status',m.learning.trade_outcome_status);section(p,'AI dispatch · '+d.sources.dispatch.state);row(p,'Readiness',m.dispatch.status);row(p,'Live AI enabled',m.live_ai_enabled);section(p,'Experience · '+d.sources.experience.state);row(p,'Historical evidence',m.experience.historical_evidence_status);row(p,'Synthetic validated',m.experience.synthetic_scorecard?.valid);row(p,'Verified historical trades',m.experience.historical_verified_subset?.verified_trades);markets.append(p)}
document.getElementById('notice').textContent='Updated '+new Date(d.checked_at*1000).toLocaleString()}
let lastData=null,paused=false;
const colors=['#69c8ac','#e9b466','#74a7e8','#c49bea','#8395aa'];
const $=id=>document.getElementById(id);
const allowed=s=>$('marketFilter').value==='all'||$('marketFilter').value===s;
const count=v=>Number.isSafeInteger(v)&&v>=0?v:0;
function panel(title,cls='panel'){const p=el('article',undefined,cls);p.append(el('h2',title));return p}
function donut(title,items,caption){const p=panel(title),total=items.reduce((n,x)=>n+count(x[1]),0);let at=0;const parts=items.map((x,i)=>{let prev=at;at+=total?count(x[1])/total*100:0;return colors[i%colors.length]+' '+prev+'% '+at+'%'});const r=el('div',undefined,'ring');r.style.background=total?'conic-gradient('+parts.join(',')+')':'#304157';const core=el('div',undefined,'ringcore');core.append(el('span',total),el('small','records'));r.append(core);p.append(r);items.forEach((x,i)=>{let l=el('div',undefined,'legend'),dot=el('i');dot.style.background=colors[i%colors.length];l.append(dot,el('span',x[0]),el('span',count(x[1])));p.append(l)});p.append(el('p',caption,'muted'));return p}
function bar(p,label,n,total,color){row(p,label,count(n)+' / '+count(total));const t=el('div',undefined,'track'),b=el('b');b.style.width=(total?Math.min(100,100*count(n)/total):0)+'%';b.style.background=color;t.append(b);p.append(t)}
function freshness(a){return (a?.state||'unavailable')+(a?.age_seconds==null?'':' · '+a.age_seconds+'s old')}
const cols=['symbol','decision_action','horizon_minutes','observed','pending','missing','distinct_observed_events','mean_signal_direction_return_pct'];
function groups(d){return (d.analytics?.paper?.groups||[]).filter(g=>allowed(g.symbol)&&($('horizonFilter').value==='all'||String(g.horizon_minutes)===$('horizonFilter').value)&&($('actionFilter').value==='all'||g.decision_action===$('actionFilter').value))}
function advance(d){
 const a=d.analytics||{},target=$('advanced');target.replaceChildren();const overview=$('overviewKpis'),accounts=$('accountAnalytics');overview.replaceChildren();accounts.replaceChildren();
 const selected=Object.keys(d.markets).filter(allowed),k=el('div',undefined,'tiles');
 const budget=a.campaign?.budget||{};
 for(const [label,value,detail] of [['AI campaign',fmt(budget.reserved)+' / '+fmt(budget.limit),freshness(a.campaign)],['Research feeds',Object.values(d.sources).filter(x=>x.state==='fresh').length+' / '+Object.keys(d.sources).length,'Fresh source reports'],['Execution','Not authorized','Research only']]){
 const p=el('div',undefined,'tile');p.append(el('span',label,'sub'),el('div',value,'kpi'),el('span',detail,'muted'));k.append(p)}
 overview.append(k);
 for(const s of selected){
 target.append(el('h2',s==='BTCUSD'?'Bitcoin intelligence':'Gold intelligence'));
 const charts=el('div',undefined,'charts'),p=a.paper?.markets?.[s],e=a.equity?.markets?.[s],h=a.settlement?.markets?.[s];
 if(p&&a.paper.state!=='unavailable'){
 charts.append(donut('AI response quality',[['Validated',p.validated_paper_proposal],['Unknown',p.transport_outcome_unknown],['Rejected',p.response_rejected],['Reserved',p.reserved_outcome_unknown]],freshness(a.paper)+' · Not trading accuracy'));
 charts.append(donut('AI decision mix',[['LONG',p.LONG],['SHORT',p.SHORT],['WAIT',p.WAIT]],'Validated paper decisions only'));
 charts.append(donut('Signal learning',[['Observed',p.path_observed],['Pending',p.path_pending],['Missing',p.path_missing_candles]],'Counterfactual paths, not trade P&L'));
 }else charts.append(panel('Paper research unavailable'));
 const q=panel('Subaccount equity · USD');q.append(el('p',freshness(a.equity),'muted'));
 for(const [label,key] of [['Capital movements','net_capital_flow_usd'],['Transfer-adjusted change','adjusted_equity_change_usd'],['Posted trading cashflow','posted_trading_cashflow_usd'],['Unexplained / unrealized','unexplained_or_unrealized_change_usd']])row(q,label,e?.[key]);
 q.append(el('p','Prospective diagnostic, not verified trade returns.','muted'));const ac=el('div',undefined,'charts');accounts.append(el('h2',s==='BTCUSD'?'Bitcoin account':'Gold account'),ac);ac.append(q);
 const z=panel('Historical settlement evidence');z.append(el('p',freshness(a.settlement),'muted'));
 if(h?.status==='complete_broker_window'){bar(z,'Verified closed',h.verified_closed,h.fire_receipts,colors[0]);bar(z,'Unverified or open',h.unverified_or_open,h.fire_receipts,colors[1]);row(z,'No order submitted',h.reasons?.broker_order_not_submitted);row(z,'Ambiguous wallet attribution',h.reasons?.unattributed_wallet_posting);row(z,'Verified subset P&L (USD)',h.verified_subset_net_usd)}else row(z,'Status',h?.status);ac.append(z);
 target.append(charts);
 }
 const tablePanel=panel('Learning explorer'),wrap=el('div',undefined,'tablewrap'),table=el('table'),head=el('thead'),tr=el('tr');
 ['Market','AI action','Minutes','Observed','Pending','Missing','Distinct events','Mean signal %'].forEach(x=>tr.append(el('th',x)));head.append(tr);table.append(head);
 const body=el('tbody');for(const g of paged('learning',groups(d),tablePanel,()=>advance(lastData),10)){const r=el('tr');for(const c of cols)r.append(el('td',c===cols[7]&&typeof g[c]==='number'?g[c].toFixed(3):fmt(g[c])));body.append(r)}table.append(body);wrap.append(table);tablePanel.prepend(wrap);tablePanel.append(el('p','Filters apply to this table. Small and overlapping samples are not model scores. '+freshness(a.paper),'muted'));target.append(tablePanel);
}
const originalRender=render;
function display(d){lastData=d;const filter=$('signalFilter').value.toLowerCase();const view={...d,markets:{}};for(const [s,m] of Object.entries(d.markets)){if(!allowed(s))continue;view.markets[s]={...m,scanner:{...m.scanner,signals:(m.scanner.signals||[]).filter(x=>[x.id,x.frame,x.direction].join(' ').toLowerCase().includes(filter))}}}originalRender(view);advance(d)}
for(const id of ['marketFilter','horizonFilter','actionFilter','signalFilter'])$(id).addEventListener('input',()=>{resetPages('learning');resetPages('signal:');if(lastData)display(lastData)});
$('manualRefresh').onclick=()=>refresh();
$('pauseRefresh').onclick=()=>{paused=!paused;$('pauseRefresh').textContent=paused?'Resume auto-refresh':'Pause auto-refresh';if(!paused)refresh()};
$('exportCsv').onclick=()=>{if(!lastData)return;const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';const csv=[cols.join(','),...groups(lastData).map(g=>cols.map(c=>quote(g[c])).join(','))].join('\r\n');const u=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));const a=el('a');a.href=u;a.download='tradebot-paper-learning.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};

async function refresh(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);display(await r.json())}catch(e){document.getElementById('notice').textContent='Status unavailable — '+String(e.message||e)+' — refresh or sign in again'}}refresh();setInterval(()=>{if(!paused)refresh()},15000);
let candleData=null,strategyData=null,workspaceSeq=0,chartGeometry=null;
const chartTime=t=>new Date(t*1000).toLocaleString();
const num=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:3}):'Unknown';
function drawMarket(){
 const canvas=$('marketCanvas'),c=canvas.getContext('2d');if(!c)return;
 const ratio=Math.min(2,devicePixelRatio||1),W=Math.max(200,canvas.clientWidth),H=350;
 canvas.width=Math.floor(W*ratio);canvas.height=Math.floor(H*ratio);c.scale(ratio,ratio);
 chartGeometry=null;
 const a=candleData,bars=a?.bars?.slice(-Number($('chartRange').value))||[];
 if(!bars.length){c.fillStyle='#9cafc5';c.fillText('No completed candles available',16,30);return}
 const L=12,R=76,T=18,B=H-26,V=$('chartVolume').checked?64:0,P=B-V;
 const hi=Math.max(...bars.map(b=>b.high)),lo=Math.min(...bars.map(b=>b.low)),pad=Math.max((hi-lo)*.06,hi*.00001);
 const y=v=>T+(hi+pad-v)/(hi-lo+2*pad)*(P-T),slot=(W-L-R)/bars.length,x=i=>L+(i+.5)*slot;
 const maxVol=Math.max(1,...bars.map(b=>b.volume));c.font='11px system-ui';c.lineWidth=1;
 for(let i=0;i<=4;i++){let yy=T+(P-T)*i/4;c.strokeStyle='#28394d';c.beginPath();c.moveTo(L,yy);c.lineTo(W-R,yy);c.stroke();c.fillStyle='#a6b7ca';c.fillText(num(hi+pad-(hi-lo+2*pad)*i/4),W-R+5,yy+3)}
 bars.forEach((b,i)=>{let xx=x(i),bw=Math.max(1,slot*.65);c.strokeStyle=c.fillStyle=b.close>=b.open?'#69c8ac':'#e98b86';c.beginPath();c.moveTo(xx,y(b.high));c.lineTo(xx,y(b.low));c.stroke();c.fillRect(xx-bw/2,Math.min(y(b.open),y(b.close)),bw,Math.max(1,Math.abs(y(b.open)-y(b.close))));if(V){c.globalAlpha=.55;let vh=b.volume/maxVol*(V-8);c.fillRect(xx-bw/2,B-vh,bw,vh);c.globalAlpha=1}
 if(i&&b.time-bars[i-1].time!==a.step){c.strokeStyle='#e9b466';c.setLineDash([3,3]);c.beginPath();c.moveTo(xx-slot/2,T);c.lineTo(xx-slot/2,B);c.stroke();c.setLineDash([])}});
 if($('chartMA').checked){c.strokeStyle='#74a7e8';c.lineWidth=1.6;c.beginPath();let started=false;bars.forEach((b,i)=>{let window=bars.slice(Math.max(0,i-19),i+1);if(window.length<20||b.time-window[0].time!==19*a.step){started=false;return}let mean=window.reduce((n,v)=>n+v.close,0)/20;if(started)c.lineTo(x(i),y(mean));else c.moveTo(x(i),y(mean));started=true});c.stroke()}
 c.fillStyle='#a6b7ca';c.fillText(chartTime(bars[0].time),L,H-7);c.textAlign='right';c.fillText(chartTime(bars.at(-1).time),W-R,H-7);c.textAlign='left';
 chartGeometry={bars,L,slot};
 $('chartInfo').textContent=a.symbol+' · '+a.frame+' · '+bars.length+' closed candles · last close '+chartTime(a.last_closed_at)+' · '+a.gaps+' missing intervals in loaded window · '+(a.checked_at-a.last_closed_at>=a.step?'historical / delayed':'latest closed interval');
}
function showStrategies(){
 const body=$('strategyTable').tBodies[0];body.replaceChildren();const a=strategyData;
 if(!a){$('strategyInfo').textContent='Strategy report unavailable';return}
 const cost=$('strategyCost').value,side=$('strategySide').value,filter=$('strategySearch').value.toLowerCase(),sort=$('strategySort').value;
 const rows=a.rows.filter(r=>(side==='all'||side===r.side)&&(!$('strategyAdequate').checked||r.samples>=30)&&[r.rule_id,r.name,r.frame].join(' ').toLowerCase().includes(filter));
 rows.sort((a,b)=>sort==='rule'?a.rule_id.localeCompare(b.rule_id):sort==='mean'?(b.costs[cost]?.mean_pct??-Infinity)-(a.costs[cost]?.mean_pct??-Infinity):b.samples-a.samples);
 $('strategyInfo').textContent=a.symbol+' · '+rows.length+' / '+a.rows.length+' rows · '+a.state+' report · '+chartTime(a.checked_at)+(rows.length?' · window '+chartTime(rows[0].start)+' – '+chartTime(rows[0].end):'');
 const nav=$('strategyPager');nav.replaceChildren();for(const r of paged('strategy',rows,nav,showStrategies,10)){const k=r.costs[cost]||{},tr=el('tr'),vals=[r.rule_id+' · '+r.name,r.frame,r.side,r.samples,num(k.mean_pct),r.samples&&typeof k.positive==='number'?num(100*k.positive/r.samples):'Unknown',num(k.sequence_drawdown_pct_points),r.sample_status==='insufficient_sample'?'Small sample':r.sample_status];vals.forEach((v,i)=>{let td=el('td',fmt(v));if(i===4&&typeof k.mean_pct==='number')td.className=k.mean_pct>=0?'positive':'negative';tr.append(td)});body.append(tr)}
}
async function workspaceRefresh(){
 const seq=++workspaceSeq,s=$('chartSymbol').value,f=$('chartFrame').value;candleData=null;strategyData=null;
 $('chartInfo').textContent='Loading '+s+' · '+f;$('candleDetail').textContent='Move over candles to inspect OHLCV.';drawMarket();showStrategies();
 const get=async url=>{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json()};
 const results=await Promise.allSettled([get('/api/chart?symbol='+encodeURIComponent(s)+'&frame='+encodeURIComponent(f)),get('/api/strategies?symbol='+encodeURIComponent(s))]);
 if(seq!==workspaceSeq)return;
 candleData=results[0].status==='fulfilled'?results[0].value:null;strategyData=results[1].status==='fulfilled'?results[1].value:null;
 if(!candleData)$('chartInfo').textContent='Chart unavailable — '+String(results[0].reason?.message||'request failed');else if(!candleData.bars.length)$('chartInfo').textContent='No completed candles';
 drawMarket();showStrategies()
}
for(const id of ['chartSymbol','chartFrame'])$(id).onchange=workspaceRefresh;
$('chartReload').onclick=workspaceRefresh;
for(const id of ['chartRange','chartMA','chartVolume'])$(id).onchange=drawMarket;
for(const id of ['strategyCost','strategySide','strategySort','strategyAdequate','strategySearch'])$(id).addEventListener('input',()=>{resetPages('strategy');showStrategies()});
$('marketCanvas').addEventListener('pointermove',e=>{if(!chartGeometry)return;const g=chartGeometry,i=Math.floor((e.offsetX-g.L)/g.slot),b=g.bars[i];if(b)$('candleDetail').textContent=chartTime(b.time)+' · O '+num(b.open)+' H '+num(b.high)+' L '+num(b.low)+' C '+num(b.close)+' V '+num(b.volume)});
window.addEventListener('resize',drawMarket);
workspaceRefresh();
let accountData=null,accountSeq=0;
function drawAccount(){
 const cv=$('accountCanvas'),c=cv.getContext('2d'),W=Math.max(cv.clientWidth,220),H=350,ratio=Math.min(2,devicePixelRatio||1);cv.width=W*ratio;cv.height=H*ratio;c.scale(ratio,ratio);
 const points=accountData?.points||[];c.font='12px system-ui';c.fillStyle='#a6b7ca';
 if(!points.length){c.fillText('No archived observations',16,24);return}
 const vs=points.flatMap(p=>[Number(p.equity_usd),Number(p.adjusted_equity_usd)]),hi=Math.max(...vs),lo=Math.min(...vs),pad=Math.max((hi-lo)*.1,Math.abs(hi)*.0001,.01);
 const y=v=>20+(hi+pad-v)/(hi-lo+2*pad)*(H-50),first=points[0].at_us,last=points.at(-1).at_us,x=t=>20+(last===first ? 0.5 : (t-first)/(last-first))*(W-100);
 for(let i=0;i<5;i++){const v=hi+pad-(hi-lo+2*pad)*i/4,yy=y(v);c.strokeStyle='#304157';c.beginPath();c.moveTo(20,yy);c.lineTo(W-80,yy);c.stroke();c.fillStyle='#a6b7ca';c.fillText(num(v),W-76,yy+4)}
 for(const [k,col] of [['equity_usd','#69c8ac'],['adjusted_equity_usd','#74a7e8']]){c.strokeStyle=c.fillStyle=col;c.lineWidth=2;c.beginPath();points.forEach((p,i)=>{const xx=x(p.at_us),yy=y(Number(p[k]));if(!i||p.at_us-points[i-1].at_us>660000000)c.moveTo(xx,yy);else c.lineTo(xx,yy)});c.stroke();points.forEach(p=>{c.beginPath();c.arc(x(p.at_us),y(Number(p[k])),3,0,Math.PI*2);c.fill()})}
 c.fillStyle='#a6b7ca';c.fillText(chartTime(first/1e6),20,H-8);
}
function positionLevel(p,n){const v=p[n];return v==null?'Unknown':fmt(v)}
function showAccount(){
 const p=$('positionView');p.replaceChildren();const a=accountData;
 $('accountInfo').textContent=a?a.symbol+' · '+a.points.length+' archived observations'+(a.points.length?' · Latest '+chartTime(a.points.at(-1).at_us/1e6):''):'Account history unavailable';
 drawAccount();if(!a)return;
 if(a.points.length){const v=a.points.at(-1);for(const [label,k] of [['Observed equity USD','equity_usd'],['Transfer-adjusted equity USD','adjusted_equity_usd'],['Capital movements USD','capital_usd'],['Posted trading cashflow USD','posted_cashflow_usd']])row(p,label,v[k])}
 const z=a.position||{};p.append(el('h3','Signed position snapshot'));
 if(z.status!=='signed_snapshot'){p.append(el('p','Position data unavailable or stale — not confirmed flat.','muted'));return}
 row(p,'Observed',new Date(z.observed_at).toLocaleString());row(p,'Open orders',z.open_order_count);
 if(!z.positions.length){p.append(el('p','No open positions at signed observation time.'));return}
 const list=el('div'),nav=el('div');p.append(list,nav);for(const q of paged('positions',z.positions,nav,showAccount,5)){const b=panel(q.side+' · '+q.size+' contracts');for(const [l,k] of [['Entry','entry'],['Mark','mark'],['Liquidation','liquidation'],['Unrealized P&L','unrealized_pnl']])row(b,l,positionLevel(q,k));row(b,'Protection',q.protection.status);row(b,'Stop loss',q.protection.stop_loss);row(b,'Take profit',q.protection.take_profit);
 const levels=[['Entry',q.entry,'#a6b7ca'],['Mark',q.mark,'#74a7e8'],['Stop',q.protection.stop_loss,'#e98b86'],['Target',q.protection.take_profit,'#69c8ac']].filter(x=>x[1]!=null&&Number.isFinite(Number(x[1]))&&Number(x[1])>0);
 if(levels.length){const low=Math.min(...levels.map(x=>Number(x[1]))),high=Math.max(...levels.map(x=>Number(x[1]))),scale=high-low||1;for(const [label,v,color] of levels){const r=el('div',undefined,'legend');r.append(el('span',label),el('span',v));b.append(r);const track=el('div',undefined,'track'),marker=el('b');marker.style.width=(5+95*(Number(v)-low)/scale)+'%';marker.style.background=color;track.append(marker);b.append(track)}}list.append(b)}
}
async function refreshAccount(){const seq=++accountSeq,s=$('accountSymbol').value;accountData=null;showAccount();try{const r=await fetch('/api/account-history?symbol='+encodeURIComponent(s),{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();if(seq!==accountSeq)return;accountData=d}catch(e){if(seq!==accountSeq)return}showAccount()}
$('accountSymbol').onchange=refreshAccount;$('accountReload').onclick=refreshAccount;window.addEventListener('resize',drawAccount);
function calculateSandbox(){
 const p=$('calcResult');p.replaceChildren();const get=id=>$(id).value.trim()===''?NaN:Number($(id).value),e=get('calcEntry'),n=get('calcQty'),u=get('calcUnit'),lev=get('calcLev'),sl=get('calcStop'),tp=get('calcTarget'),sign=$('calcSide').value==='LONG'?1:-1;
 if(![e,n,u,lev].every(v=>Number.isFinite(v)&&v>0)||!Number.isSafeInteger(n)||lev<1){p.append(el('p','Enter positive assumptions and whole contracts.','muted'));return}
 const notional=e*n*u;if(!Number.isFinite(notional)){p.append(el('p','Assumptions exceed numeric range.'));return}
 row(p,'Hypothetical notional USD',num(notional));row(p,'Simple margin (notional / leverage)',num(notional/lev));
 if(Number.isFinite(sl)&&sl>0&&Number.isFinite(tp)&&tp>0&&sign*(e-sl)>0&&sign*(tp-e)>0){const loss=sign*(e-sl)*n*u,reward=sign*(tp-e)*n*u;row(p,'Hypothetical stop loss USD',num(loss));row(p,'Hypothetical target gain USD',num(reward));row(p,'Reward / risk',num(reward/loss))}
 else p.append(el('p','Enter correctly oriented stop and target for bracket arithmetic.','muted'));
}
for(const id of ['calcEntry','calcQty','calcUnit','calcLev','calcSide','calcStop','calcTarget'])$(id).addEventListener('input',calculateSandbox);
calculateSandbox();refreshAccount();

let activeTab='home';
function switchTab(tab){
 if(!['home','charts','strategy','ai','accounts','tools'].includes(tab))return;
 activeTab=tab;
 document.querySelectorAll('[data-view]').forEach(n=>n.hidden=n.dataset.view!==tab);
 document.querySelectorAll('[data-tab]').forEach(n=>n.setAttribute('aria-current',n.dataset.tab===tab?'page':'false'));
 $('researchToolbar').hidden=!['home','ai','accounts'].includes(tab);
 $('horizonFilter').closest('label').hidden=tab!=='ai';$('actionFilter').closest('label').hidden=tab!=='ai';$('exportCsv').hidden=tab!=='ai';$('signalFilter').hidden=tab!=='home';
 if(tab==='charts')drawMarket();if(tab==='accounts')refreshAccount();if(tab==='strategy')showStrategies();
 window.scrollTo(0,0);
}
document.querySelectorAll('[data-tab]').forEach(n=>n.onclick=()=>switchTab(n.dataset.tab));
$('strategySymbol').onchange=()=>{$('chartSymbol').value=$('strategySymbol').value;resetPages('strategy');workspaceRefresh()};
$('chartSymbol').addEventListener('change',()=>{$('strategySymbol').value=$('chartSymbol').value;resetPages('strategy')});
switchTab('home');
