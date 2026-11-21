const state = { data: [], filtered: [], sortKey: 'score', sortDir: -1, selected: null, setup: 'all', group: 'all', query: '', watchOnly: false, favorites: [] };
const $ = (s) => document.querySelector(s);
const svgNS = 'http://www.w3.org/2000/svg';
const setupNames = { 'Momentum':'动量成立', 'Strong / wait pullback':'加速强势', 'Pullback watch':'等待确认', 'Avoid / broken':'趋势破坏', 'Absolute up':'绝对动量成立', 'Absolute down':'绝对动量不成立' };

// Chinese display labels describe each fund; not official legal names.
const payload=JSON.parse(document.getElementById('dataset').textContent);
const etfNames=Object.fromEntries(payload.rows.map(r=>[r.ticker,r.name]));
const etfName=ticker=>escapeHTML(etfNames[ticker]||ticker);
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const pct=v=>finite(v)?`${v>=0?'+':''}${(v*100).toFixed(1)}%`:'—';
const price=v=>finite(v)?v.toLocaleString('zh-CN',{minimumFractionDigits:3,maximumFractionDigits:3}):'—';
const cls=v=>finite(v)?v>=0?'positive':'negative':'';
const scoreText=v=>finite(v)?v.toFixed(1):'—';
const statusClass=s=>(s==='Momentum'||s==='Strong / wait pullback')?'momentum':(s==='Pullback watch'||s==='Absolute up')?'wait':'avoid';
const escapeHTML=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
setupNames['Data unavailable']='数据不足 / 日期不齐';
let previousFocus=null;

function renderKPIs(){
  // Breadth = domestic equity ETFs only (no bonds, commodities, HK or overseas).
  const d=state.data.filter(x=>x.eligible&&x.asset_class==='equity'&&x.market==='境内'), n=d.length;
  const complete=state.data.filter(x=>x.eligible).length;
  const cards=[
    ['扫描范围',state.data.length,'只 ETF',`${complete} 只满足完整窗口 · 宽度按 A股权益 ${n} 只`],
    ['20日上涨',d.filter(x=>x.r20>0).length,`/ ${n}`,`${Math.round(d.filter(x=>x.r20>0).length/Math.max(n,1)*100)}% 短线宽度`],
    ['60日上涨',d.filter(x=>x.r60>0).length,`/ ${n}`,`${Math.round(d.filter(x=>x.r60>0).length/Math.max(n,1)*100)}% 中期宽度`],
    ['多头排列',d.filter(x=>x.trend_aligned===true).length,`/ ${n}`,'Close > 20EMA > 50MA > 120MA']
  ];
  $('#kpiGrid').innerHTML=cards.map(c=>`<article class="kpi-card"><p class="kpi-label">${c[0]}</p><div class="kpi-value">${c[1]} <small>${c[2]}</small></div><p class="kpi-foot">${c[3]}</p></article>`).join('');
  const periods=[20,60,120];
  $('#breadthBars').innerHTML=periods.map(p=>{const v=d.filter(x=>x[`r${p}`]>0).length/Math.max(n,1)*100;return `<div class="breadth-item"><span>${p}D</span><div class="breadth-track"><div class="breadth-fill" style="width:${v}%"></div></div><b>${Math.round(v)}%</b></div>`}).join('');
  const breadth=periods.map(p=>n?d.filter(x=>x[`r${p}`]>0).length/n:0);
  const [title,copy]=marketRegime(breadth,n);
  $('#regimeTitle').textContent=title;$('#regimeCopy').textContent=copy;

}

function setupMatch(x){
  if(state.setup==='all') return true;
  if(state.setup==='actionable') return x.setup==='Momentum'||x.setup==='Strong / wait pullback';
  if(state.setup==='watch') return x.setup==='Pullback watch';
  return x.setup==='Avoid / broken'||x.setup==='Data unavailable';
}
function applyFilters(){
  state.filtered=state.data.filter(x=>(!state.watchOnly||state.favorites.includes(x.ticker))&&(state.group==='all'||x.group===state.group)&&setupMatch(x)&&`${x.ticker} ${etfName(x.ticker)}`.toLowerCase().includes(state.query));
  state.filtered.sort((a,b)=>{const av=a[state.sortKey],bv=b[state.sortKey];if(!finite(av)&&typeof av!=='string')return 1;if(!finite(bv)&&typeof bv!=='string')return -1;return typeof av==='number'?(av-bv)*state.sortDir:String(av).localeCompare(String(bv))*state.sortDir});
  renderTable(); renderScatter(); renderLeaders(); renderOpportunities(); renderSectors(); savePreferences();
  document.querySelectorAll('th[data-sort]').forEach(th=>th.setAttribute('aria-sort',th.dataset.sort===state.sortKey?(state.sortDir===1?'ascending':'descending'):'none'));
  $('#watchOnly').setAttribute('aria-pressed',String(state.watchOnly));
}

function renderScatter(){
  const host=$('#scatterChart'); host.innerHTML='';
  const data=state.filtered.filter(x=>x.eligible);
  const W=Math.max(320,host.clientWidth||700),H=340,m={l:48,r:22,t:18,b:42};
  const svg=document.createElementNS(svgNS,'svg'); svg.setAttribute('viewBox',`0 0 ${W} ${H}`); host.append(svg);
  if(!data.length){svg.innerHTML=`<text x="50%" y="50%" text-anchor="middle" fill="#718096">没有符合条件的 ETF</text>`;return;}
  const xs=data.map(x=>x.r60*100),ys=data.map(x=>x.r20*100);
  let xmin=Math.min(-2,...xs),xmax=Math.max(2,...xs),ymin=Math.min(-2,...ys),ymax=Math.max(2,...ys);
  const xp=(v)=>m.l+(v-xmin)/(xmax-xmin)*(W-m.l-m.r), yp=(v)=>H-m.b-(v-ymin)/(ymax-ymin)*(H-m.t-m.b);
  for(let i=0;i<=5;i++){
    const xv=xmin+(xmax-xmin)*i/5,yv=ymin+(ymax-ymin)*i/5;
    const vl=document.createElementNS(svgNS,'line');vl.setAttribute('x1',xp(xv));vl.setAttribute('x2',xp(xv));vl.setAttribute('y1',m.t);vl.setAttribute('y2',H-m.b);vl.setAttribute('class',Math.abs(xv)<.01?'zero-line':'grid-line');svg.append(vl);
    const ht=document.createElementNS(svgNS,'text');ht.setAttribute('x',xp(xv));ht.setAttribute('y',H-16);ht.setAttribute('text-anchor','middle');ht.setAttribute('class','axis-label');ht.textContent=`${xv.toFixed(0)}%`;svg.append(ht);
    const hl=document.createElementNS(svgNS,'line');hl.setAttribute('x1',m.l);hl.setAttribute('x2',W-m.r);hl.setAttribute('y1',yp(yv));hl.setAttribute('y2',yp(yv));hl.setAttribute('class',Math.abs(yv)<.01?'zero-line':'grid-line');svg.append(hl);
    const vt=document.createElementNS(svgNS,'text');vt.setAttribute('x',m.l-9);vt.setAttribute('y',yp(yv)+4);vt.setAttribute('text-anchor','end');vt.setAttribute('class','axis-label');vt.textContent=`${yv.toFixed(0)}%`;svg.append(vt);
  }
  const xlab=document.createElementNS(svgNS,'text');xlab.setAttribute('x',(m.l+W-m.r)/2);xlab.setAttribute('y',H-1);xlab.setAttribute('text-anchor','middle');xlab.setAttribute('class','axis-label');xlab.textContent='60日收益';svg.append(xlab);
  [[xp(0),m.t,xp(0),H-m.b],[m.l,yp(0),W-m.r,yp(0)]].forEach(coords=>{const line=document.createElementNS(svgNS,'line');['x1','y1','x2','y2'].forEach((a,i)=>line.setAttribute(a,coords[i]));line.setAttribute('class','zero-line');svg.append(line);});
  const sorted=[...data].sort((a,b)=>a.adtv20-b.adtv20), labels=new Set([...data].filter(x=>finite(x.score)).sort((a,b)=>b.score-a.score).slice(0,W<500?4:10).map(x=>x.ticker));
  sorted.forEach(x=>{
    const t=Math.max(0,Math.min(1,(x.r120+.15)/.7)); const r=5+Math.max(0,Math.min(7,Math.log10(Math.max(x.adtv20||1e6,1e6)/1e6)*1.3));
    const dot=document.createElementNS(svgNS,'circle');dot.setAttribute('cx',xp(x.r60*100));dot.setAttribute('cy',yp(x.r20*100));dot.setAttribute('r',r);dot.setAttribute('fill',`hsl(${350+t*150} 70% 57%)`);dot.setAttribute('fill-opacity','.78');dot.setAttribute('stroke','#0d1420');dot.setAttribute('class','dot');dot.setAttribute('tabindex','0');
    dot.setAttribute('role','button');dot.setAttribute('aria-label',`${x.ticker} ${etfName(x.ticker)} 评分 ${scoreText(x.score)}`);dot.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openDrawer(x);}});dot.addEventListener('click',()=>openDrawer(x)); dot.addEventListener('mouseenter',e=>showTip(e,x));dot.addEventListener('mousemove',moveTip);dot.addEventListener('mouseleave',hideTip);svg.append(dot);
    if(labels.has(x.ticker)){const lab=document.createElementNS(svgNS,'text');lab.setAttribute('x',xp(x.r60*100)+r+3);lab.setAttribute('y',yp(x.r20*100)-r+2);lab.setAttribute('class','dot-label');lab.textContent=x.ticker;svg.append(lab);}
  });
}

function renderLeaders(){
  const top=state.filtered.filter(x=>x.eligible&&finite(x.score)).sort((a,b)=>b.score-a.score).slice(0,10),max=Math.max(...top.map(x=>x.score),1);
  $('#leaderList').innerHTML=top.map(x=>`<div class="leader" data-code="${x.ticker}"><span class="leader-identity"><span class="leader-code">${x.ticker}</span><span class="leader-name">${etfName(x.ticker)}</span><span class="table-chip ${statusClass(x.setup)}">${setupNames[x.setup]}</span></span><div class="leader-track"><div class="leader-fill" style="width:${x.score/max*100}%">${pct(x.r60)}</div></div><span class="leader-score">${scoreText(x.score)}</span></div>`).join('');
  document.querySelectorAll('.leader').forEach(el=>el.addEventListener('click',()=>openDrawer(state.data.find(x=>x.ticker===el.dataset.code))));
}

function renderOpportunities(){
  const picks=state.filtered.filter(x=>x.setup==='Momentum').sort((a,b)=>b.score-a.score).slice(0,5);
  $('#opportunityGrid').innerHTML=picks.map(x=>`<article class="opp-card" data-code="${x.ticker}"><div class="opp-top"><span class="opp-identity"><span class="opp-code">${x.ticker}</span><span class="opp-name">${etfName(x.ticker)}</span></span><span class="opp-price">¥${price(x.close)}</span></div><span class="status-chip">${setupNames[x.setup]}</span><div class="return-row">${[20,60,120].map(p=>`<div class="return-cell"><span>${p}日</span><strong class="${cls(x[`r${p}`])}">${pct(x[`r${p}`])}</strong></div>`).join('')}</div><div class="level-row"><span>回踩区</span><b>${price(x.pullback_low)}–${price(x.pullback_high)}</b></div><div class="level-row"><span>突破触发</span><b>${price(x.breakout_trigger)}</b></div><div class="level-row"><span>失效参考</span><b>${price(x.stop_ref)}</b></div></article>`).join('');
  if(!picks.length)$('#opportunityGrid').innerHTML='<p class="empty-note">当前筛选没有符合全部动量条件的ETF，可切换至「等待确认」继续观察。</p>';
  document.querySelectorAll('.opp-card').forEach(el=>el.addEventListener('click',()=>openDrawer(state.data.find(x=>x.ticker===el.dataset.code))));
}

function renderTable(){
  $('#resultCount').textContent=`显示 ${state.filtered.length} / ${state.data.length} 只`;
  $('#tableBody').innerHTML=state.filtered.map(x=>`<tr data-code="${x.ticker}" tabindex="0" role="button" aria-label="查看${x.ticker}详情"><td><button class="favorite" data-favorite="${x.ticker}" aria-label="${state.favorites.includes(x.ticker)?'取消收藏':'收藏'}${x.ticker}" aria-pressed="${state.favorites.includes(x.ticker)}">${state.favorites.includes(x.ticker)?'★':'☆'}</button></td><td class="ticker-cell"><span class="ticker-code">${x.ticker}</span><span class="ticker-name">${etfName(x.ticker)}${premiumChip(x)}${weeklySet.has(x.ticker)?'<span class="pick-chip">周清单</span>':''}</span></td><td class="group-label">${escapeHTML(x.group)}</td><td class="num">¥${price(x.close)}</td><td class="num ${cls(x.r20)}">${pct(x.r20)}</td><td class="num ${cls(x.r60)}">${pct(x.r60)}</td><td class="num ${cls(x.r120)}">${pct(x.r120)}</td><td class="num ${cls(x.rs60)}">${pct(x.rs60)}</td><td class="num">${(finite(x.atr_pct)?(x.atr_pct*100).toFixed(1):'—')}%</td><td class="num ${x.near_high250===0?'positive':''}">${finite(x.near_high250)?(x.near_high250===0?'新高':pct(x.near_high250)):'—'}</td><td class="num score-cell">${scoreText(x.score)}</td><td class="rank-change">${rankChange(x.ticker)}</td><td><span class="table-chip ${statusClass(x.setup)}">${setupNames[x.setup]}</span></td></tr>`).join('');
  document.querySelectorAll('[data-favorite]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();const t=b.dataset.favorite;state.favorites=state.favorites.includes(t)?state.favorites.filter(v=>v!==t):[...state.favorites,t];applyFilters();}));
  if(!state.filtered.length)$('#tableBody').innerHTML='<tr><td colspan="13" class="empty-note">没有符合条件的 ETF；可重置筛选或取消「仅看自选」。</td></tr>';
  document.querySelectorAll('#tableBody tr[data-code]').forEach(el=>{const open=()=>openDrawer(state.data.find(x=>x.ticker===el.dataset.code));el.addEventListener('click',open);el.addEventListener('keydown',e=>{if(e.target===el&&e.key==='Enter')open();});});
}

function openDrawer(x){
  if(!x)return; previousFocus=document.activeElement;state.selected=x;
  $('#drawerContent').innerHTML=`<p class="section-kicker">ETF DETAIL</p><h2 class="detail-code">${x.ticker}</h2><p class="detail-meta">${etfName(x.ticker)}</p><p class="detail-meta">${escapeHTML(x.group)} · ${x.date||'无有效日期'} · ${x.cached?'同源缓存':'同花顺前复权日线'} · 收盘 ¥${price(x.close)}</p><div class="detail-score"><b>${scoreText(x.score)}</b><span>综合动量评分</span></div><div class="detail-grid">${[["20日收益",pct(x.r20),cls(x.r20)],["60日收益",pct(x.r60),cls(x.r60)],["120日收益",pct(x.r120),cls(x.r120)],["60日相对沪深300",pct(x.rs60),cls(x.rs60)],["ATR / 价格",`${(finite(x.atr_pct)?(x.atr_pct*100).toFixed(2):'—')}%`,''],["距120日高点",pct(x.from_high120),cls(x.from_high120)]].map(v=>`<div class="detail-stat"><span>${v[0]}</span><b class="${v[2]}">${v[1]}</b></div>`).join('')}</div>${premiumDetail(x)}<div class="trade-plan"><h3>${setupNames[x.setup]}</h3><div class="trade-step"><i>01</i><div>${x.setup==='Strong / wait pullback'?`距EMA20超过2.5倍ATR，处于加速段；回踩区 <b>${price(x.pullback_low)}–${price(x.pullback_high)}</b> 仅作参考，2022–2026年回测中此类状态之后未见系统性回落，追高波动也更大。`:`回踩观察区 <b>${price(x.pullback_low)}–${price(x.pullback_high)}</b>，观察是否止跌。`}</div></div><div class="trade-step"><i>02</i><div>趋势延续的突破触发参考为 <b>${price(x.breakout_trigger)}</b>。</div></div><div class="trade-step"><i>03</i><div>结构失效参考 <b>${price(x.stop_ref)}</b>；当前至该位置约 <b>${pct(x.stop_pct)}</b>。</div></div></div>${exposureDetail(x)}`;
  $('#detailDrawer').inert=false;$('#detailDrawer').classList.add('open');$('#drawerBackdrop').classList.add('open');$('#detailDrawer').setAttribute('aria-hidden','false');$('#drawerClose').focus();
}
function closeDrawer(){ $('#detailDrawer').classList.remove('open');$('#drawerBackdrop').classList.remove('open');$('#detailDrawer').setAttribute('aria-hidden','true');$('#detailDrawer').inert=true;previousFocus?.focus(); }
function showTip(e,x){$('#tooltip').innerHTML=`<b>${x.ticker}</b> · 评分 ${scoreText(x.score)}<br>20D ${pct(x.r20)} · 60D ${pct(x.r60)} · 120D ${pct(x.r120)}`;$('#tooltip').style.display='block';moveTip(e);}
function moveTip(e){$('#tooltip').style.left=`${Math.min(innerWidth-230,e.clientX+13)}px`;$('#tooltip').style.top=`${e.clientY+13}px`;}
function hideTip(){$('#tooltip').style.display='none';}

function bind(){
  $('#watchOnly').addEventListener('click',()=>{state.watchOnly=!state.watchOnly;applyFilters();});
  $('#resetFilters').addEventListener('click',()=>{Object.assign(state,{query:'',group:'all',setup:'all',watchOnly:false,sortKey:'score',sortDir:-1});syncControls();applyFilters();});
  $('#searchInput').addEventListener('input',e=>{state.query=e.target.value.trim().toLowerCase();applyFilters();});
  $('#groupSelect').addEventListener('change',e=>{state.group=e.target.value;applyFilters();});
  document.querySelectorAll('#setupFilter button').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('#setupFilter button').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.setup=b.dataset.setup;syncControls();applyFilters();}));
  document.querySelectorAll('th[data-sort]').forEach(th=>th.addEventListener('click',()=>{const key=th.dataset.sort;state.sortDir=state.sortKey===key?-state.sortDir:(['ticker','group','setup'].includes(key)?1:-1);state.sortKey=key;applyFilters();}));
  $('#drawerClose').addEventListener('click',closeDrawer);$('#drawerBackdrop').addEventListener('click',closeDrawer);addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer();if(e.key==='Tab'&&$('#detailDrawer').classList.contains('open'))trapFocus(e);});
  let timer;addEventListener('resize',()=>{clearTimeout(timer);timer=setTimeout(renderScatter,120);});
}

function renderSectors(){
 const groups=[...new Set(state.data.map(x=>x.group))].map(group=>{const all=state.data.filter(x=>x.group===group),d=all.filter(x=>x.eligible),avg=k=>{const v=d.map(r=>r[k]).filter(finite);return v.length?v.reduce((s,x)=>s+x,0)/v.length:null;};return {group,count:d.length,total:all.length,score:avg('score'),returns:[20,60,120].map(n=>avg(`r${n}`)),aligned:d.filter(r=>r.trend_aligned).length};}).sort((a,b)=>(b.score??-Infinity)-(a.score??-Infinity));
 $('#sectorGrid').innerHTML='<div class="heat-row heat-head"><span>板块 / 动量分</span><span>20日</span><span>60日</span><span>120日</span><span>多头 / 有效</span></div>'+groups.map(g=>`<button type="button" class="heat-row" data-group="${escapeHTML(g.group)}"><span><b>${escapeHTML(g.group)}</b><small>评分 ${scoreText(g.score)} · ${g.count}/${g.total} 有效</small></span>${g.returns.map(v=>`<span class="heat-cell ${cls(v)}">${pct(v)}</span>`).join('')}<span>${g.aligned}/${g.count}<small>${g.count?Math.round(g.aligned/g.count*100):0}% 多头</small></span></button>`).join('');
 document.querySelectorAll('[data-group]').forEach(b=>b.addEventListener('click',()=>{state.group=b.dataset.group;syncControls();applyFilters();$('.table-section').scrollIntoView({behavior:'smooth'});}));
}
function marketRegime([b20,b60,b120],n){
 if(!n)return ['暂无有效样本','完整窗口不足，暂不判断市场强弱。'];
 if(Math.max(b20,b60,b120)<.4)return ['多数样本下跌，强势集中于少数方向','三个周期上涨比例均低于40%；周期表现一致，但不代表整体强势。'];
 if(b120>.65&&b20<.4)return ['长趋势仍在，短线动量收缩','多数样本保留120日涨幅，但短线参与度不足。'];
 if(b20>.6&&b60>.6)return ['短中期动量扩散','20日与60日上涨比例均超过60%，上涨参与度较高。'];
 if(b20>.6&&b60<.4)return ['短线回升，中期仍弱','短线参与度改善，中期趋势尚未同步恢复。'];
 return ['结构分化，等待趋势确认','各周期参与度尚未形成一致强势，结合板块与趋势状态观察。'];
}
function savePreferences(){try{localStorage.setItem('jade-preferences-v1',JSON.stringify(Object.fromEntries(['query','group','setup','sortKey','sortDir','watchOnly','favorites'].map(k=>[k,state[k]]))));}catch{}}
function restorePreferences(){try{const p=JSON.parse(localStorage.getItem('jade-preferences-v1')||'{}');
 if(typeof p.query==='string')state.query=p.query;
 if(['all',...state.data.map(x=>x.group)].includes(p.group))state.group=p.group;
 if(['all','actionable','watch','avoid'].includes(p.setup))state.setup=p.setup;
 if([...document.querySelectorAll('th[data-sort]')].some(x=>x.dataset.sort===p.sortKey))state.sortKey=p.sortKey;
 if([1,-1].includes(p.sortDir))state.sortDir=p.sortDir;
 state.watchOnly=p.watchOnly===true;state.favorites=Array.isArray(p.favorites)?p.favorites.filter(t=>state.data.some(x=>x.ticker===t)):[];
 }catch{}syncControls();}
function syncControls(){$('#searchInput').value=state.query;$('#groupSelect').value=state.group;document.querySelectorAll('#setupFilter button').forEach(b=>{b.classList.toggle('active',b.dataset.setup===state.setup);b.setAttribute('aria-pressed',String(b.dataset.setup===state.setup));});}
function rankChange(ticker){const change=payload.comparison?.changes?.[ticker];return change?change.rank_delta>0?`↑ ${change.rank_delta}`:change.rank_delta<0?`↓ ${-change.rank_delta}`:'—':'暂无';}
function renderChanges(){
 const c=payload.comparison;
 $('#comparisonDate').textContent=c?.asof?`对比 ${c.asof}`:'暂无对照';
 if(!c?.changes){$('#dailyChanges').innerHTML='<p class="empty-note">暂无同口径的较早快照。观察池扩容、有效样本变化或缓存数据均暂停比较；后续使用真实历史，不推算排名。</p>';return;}
 const items=Object.entries(c.changes),names=list=>list.length?list.slice(0,5).map(([t])=>`${etfName(t)} ${t}`).join('、'):'无';
 const rises=items.filter(([,v])=>v.rank_delta>0).sort((a,b)=>b[1].rank_delta-a[1].rank_delta);
 $('#dailyChanges').innerHTML=[['排名上升',rises.length?rises.slice(0,3).map(([t,v])=>`${etfName(t)} ↑${v.rank_delta}`).join('、'):'无'],['新进入强势',names(items.filter(([,v])=>v.entered_strong))],['新转为趋势破坏',names(items.filter(([,v])=>v.broken))]].map(([title,text])=>`<article><span>${title}</span><p>${text}</p></article>`).join('');
}
function init(){
 try{
  state.data=payload.rows;state.filtered=[...state.data];
  $('#asOf').textContent=`数据截止 ${payload.asof} · 同花顺日线`;
  const invalid=state.data.filter(x=>!x.eligible).length,cached=state.data.filter(x=>x.cached).length;
  $('#dataQuality').textContent=`${payload.offline?'离线快照 · ':''}最近成功快照 ${payload.generated.replace('T',' ').replace('+08:00','')} 北京时间 · ${state.data.length-invalid}/${state.data.length} 只完整 · ${cached} 只缓存 · 基准 沪深300ETF（510300）`;
  if(invalid||cached||payload.asof<payload.requested_cutoff)$('#dataQuality').classList.add('warning');
  $('#healthSummary').textContent=`数据运行记录 · ${payload.errors.length} 条提醒`;
  $('#healthLog').innerHTML=payload.errors.length?'<ul>'+payload.errors.map(e=>`<li>${escapeHTML(e)}</li>`).join('')+'</ul>':'<p>本次同花顺行情请求全部完成。'+(cached?'存在缓存，请查看数据时间。':'未使用缓存。')+'</p>';
  const groups=[...new Set(state.data.map(x=>x.group))];$('#groupSelect').innerHTML+=groups.map(g=>`<option value="${escapeHTML(g)}">${escapeHTML(g)}</option>`).join('');
  document.querySelectorAll('th[data-sort]').forEach(th=>{th.setAttribute('tabindex','0');th.setAttribute('role','button');th.addEventListener('keydown',e=>{if(e.key==='Enter')th.click();});});
  restorePreferences();renderWeekly();renderKPIs();renderRegimeState();renderChanges();bind();applyFilters();
 }catch(err){document.querySelector('main').innerHTML=`<div class="error-state"><h2>数据载入失败</h2><p>${escapeHTML(err.message)}</p></div>`;}
}

const assetNames={equity:'权益',commodity:'商品',bond:'债券',convertible:'可转债'};
const clusterMembers=Object.fromEntries([...new Set(payload.rows.map(r=>r.cluster).filter(Boolean))].map(c=>[c,payload.rows.filter(r=>r.cluster===c).map(r=>r.ticker)]));
function premiumChip(x){
  if(!finite(x.premium)||Math.abs(x.premium)<.01)return '';
  return `<span class="premium-chip ${Math.abs(x.premium)>=.03?'hot':''}" title="收盘价相对${escapeHTML(x.nav_date||'')}单位净值">${x.premium>0?'溢价':'折价'} ${(Math.abs(x.premium)*100).toFixed(1)}%</span>`;
}
function premiumDetail(x){
  if(!('premium' in x))return '';
  if(!finite(x.premium))return '<p class="detail-note">跨境ETF：本次未取得净值，溢价暂不显示。</p>';
  const warn=Math.abs(x.premium)>=.03?'溢价变化会直接影响场内收益，动量中可能含有溢价扩张成分。':'溢折价处于常见范围。';
  return `<p class="detail-note">跨境ETF · 相对 ${escapeHTML(x.nav_date)} 单位净值 <b class="${x.premium>=.03?'negative':''}">${x.premium>0?'溢价':'折价'} ${(Math.abs(x.premium)*100).toFixed(2)}%</b>。${warn}</p>`;
}
function exposureDetail(x){
  const lines=[];
  if(x.market&&x.market!=='境内')lines.push(`${x.market==='港股'?'港股':'海外'}资产：场内价格以人民币计价，含汇率与溢价变化；不计入A股市场宽度。`);
  if(x.added)lines.push(`${escapeHTML(x.added)} 起加入观察池，从这一天起才参与周度清单，纸面跟踪不会回溯计入。`);
  if(x.cluster)lines.push(`同类暴露「${escapeHTML(x.cluster)}」：${clusterMembers[x.cluster].filter(t=>t!==x.ticker).map(t=>`${etfName(t)} ${t}`).join('、')}。近一年日收益相关性 ≥ 0.95，排名靠前时可能代表同一主题。`);
  if(x.eligible&&x.asset_class!=='equity')lines.push(`${assetNames[x.asset_class]}类资产不与股票ETF一起排名，因此没有综合评分；绝对动量 <b>${x.abs_momentum?'成立':'不成立'}</b>（120日收益高于货币ETF同期收益，且收盘在120日均线上方）。`);
  return lines.length?`<div class="shadow-panel"><h3>暴露与资产类别</h3>${lines.map(l=>`<p>${l}</p>`).join('')}</div>`:'';
}
function renderRegimeState(){
  const r=payload.regime;if(!r)return;
  const map={risk_on:['偏进攻','sector-up'],neutral:['中性','sector-flat'],risk_off:['偏防守','sector-down']};
  const [label,klass]=map[r.state]||['—',''];
  $('#regimeState').innerHTML=`<span class="regime-chip ${r.state}">双动量状态 · ${label}</span><small>沪深300 120日 ${pct(r.bench_r120)} vs 现金 ${pct(r.hurdle)}（${escapeHTML(r.hurdle_source||'')}）· A股权益60日上涨占比 ${finite(r.breadth60)?Math.round(r.breadth60*100)+'%':'—'}</small><small class="regime-caveat">仅作背景：2022–2026回测中，按大盘趋势进出（如跌破200日线换国债）跑输一直持有沪深300，因此不作为买卖信号。</small>`;
  renderIndexStrip();
}
function trapFocus(e){
  const items=[...$('#detailDrawer').querySelectorAll('button,[href],[tabindex]:not([tabindex="-1"])')].filter(el=>!el.disabled);
  if(!items.length)return;
  const first=items[0],last=items[items.length-1];
  if(!$('#detailDrawer').contains(document.activeElement)){e.preventDefault();first.focus();}
  else if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
}
const weekly=payload.weekly;
const weeklySet=new Set((weekly&&weekly.picks||[]).map(p=>p.ticker));
function navChart(nav){
  const W=520,H=150,P=8;const vals=nav.flatMap(p=>[p.s,p.b,p.e]);const lo=Math.min(1,...vals),hi=Math.max(1,...vals);
  const x=i=>P+(W-2*P)*(nav.length<2?1:i/(nav.length-1)),y=v=>H-P-(H-2*P)*((v-lo)/((hi-lo)||1));
  const line=k=>nav.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`).join('');
  return `<svg class="track-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="纸面跟踪净值"><line x1="${P}" x2="${W-P}" y1="${y(1)}" y2="${y(1)}" class="base"/><path d="${line('e')}" class="ew"/><path d="${line('b')}" class="bench"/><path d="${line('s')}" class="strat"/></svg>`;
}
function renderWeekly(){
  const box=$('#weeklySection');
  if(!weekly){box.innerHTML='<p class="empty-note">历史数据不足250个交易日，本次没有周度清单。</p>';return;}
  const when=weekly.holding_from==='next'?`下周持有 · ${escapeHTML(weekly.rebalance_date)} 收盘选出`:`本周持有 · ${escapeHTML(weekly.rebalance_date)} 收盘选出`;
  const cards=weekly.picks.map((p,i)=>`<button class="pick-card" data-code="${p.ticker}"><span class="pick-rank">${i+1}</span><b>${etfName(p.ticker)}</b><small>${p.ticker}${weekly.added.includes(p.ticker)?' · <em>新进</em>':''}</small><span class="pick-metric">${p.near_high===0?'处于250日新高':'距250日高 '+pct(p.near_high)}</span><span class="pick-sub">60日 ${pct(p.r60)}</span></button>`).join('');
  const removed=weekly.removed.length?`换出：${weekly.removed.map(t=>`${etfName(t)} ${t}`).join('、')}`:(weekly.previous_date?'与上周相同，无换出':'');
  const byCluster={};weekly.picks.forEach(p=>{const r=payload.rows.find(x=>x.ticker===p.ticker);if(r&&r.cluster)(byCluster[r.cluster]=byCluster[r.cluster]||[]).push(p.ticker);});
  const conc=Object.entries(byCluster).filter(([,v])=>v.length>=2).map(([k,v])=>`${v.length} 只属于同类暴露「${escapeHTML(k)}」`);
  const concNote=conc.length?`<p class="weekly-note warn">集中度提示：清单中 ${conc.join('，')}，近一年日收益相关性 ≥ 0.95，实际接近押注同一主题，回撤可能更大。</p>`:'';
  const prov=weekly.provisional?`<p class="weekly-note">按今日收盘，下次调仓的前5：${weekly.provisional.map(p=>etfName(p.ticker)).join('、')}（周五收盘确定）</p>`:'';
  const tr=weekly.track;
  const track=tr?`<div class="track"><div class="track-head"><b>纸面跟踪</b><span>自 ${escapeHTML(weekly.track_start)} · ${tr.weeks} 周 · 已扣单边${(weekly.cost*100).toFixed(1)}%成本</span></div>${navChart(tr.nav)}<div class="track-legend"><span class="strat">周度清单 ${pct(tr.strategy.total)}</span><span class="bench">沪深300ETF ${pct(tr.benchmark.total)}</span><span class="ew">权益ETF等权 ${pct(tr.equal_weight.total)}</span>${tr.strategy.mdd!=null?`<span>清单最大回撤 ${pct(tr.strategy.mdd)}</span>`:''}</div></div>`
    :`<div class="track"><div class="track-head"><b>纸面跟踪</b><span>自 ${escapeHTML(weekly.track_start)} 起按冻结规则记录，下一个交易日开始计入收益。</span></div></div>`;
  box.innerHTML=`<div class="panel-head"><div><p class="section-kicker">WEEKLY PICKS · 250日高点轮动</p><h2>${when}</h2></div><span class="badge">前${weekly.top_n}名 · 等权 · 每周调仓</span></div>
  <div class="pick-grid">${cards}</div>${concNote}<p class="weekly-note">${removed}</p>${prov}${track}
  <p class="weekly-note muted">规则：每周最后一个交易日，在权益类ETF中选收盘价最接近过去250日最高收盘价的5只，下周等权持有。2022-12至2026-11回测年化约+21%（同期沪深300约+3%），但观察池为事后挑选，以纸面跟踪为准。仅为规则计算结果，不构成投资建议。</p>`;
  box.querySelectorAll('.pick-card').forEach(b=>b.addEventListener('click',()=>openDrawer(state.data.find(x=>x.ticker===b.dataset.code))));
}
function renderIndexStrip(){
  const box=$('#indexStrip'),list=(payload.regime&&payload.regime.indices)||[];
  if(!list.length){box.remove();return;}
  const trendName={up:'多头排列',down:'空头排列',range:'震荡'},trendCls={up:'sector-up',down:'sector-down',range:'sector-flat'};
  const ma=x=>['50','120','250'].map(k=>`<span class="ma ${x.above[k]?'on':''}" title="收盘${x.above[k]?'高于':'低于'}${k}日均线">${k}</span>`).join('');
  const cards=list.map(x=>`<button class="index-card" data-code="${x.ticker}"><div class="index-top"><b>${escapeHTML(x.name)}</b><span class="index-trend ${trendCls[x.trend]}">${trendName[x.trend]}</span></div><div class="index-near">${finite(x.near_high)?(x.near_high===0?'250日新高':'距高点 '+pct(x.near_high)):'—'}</div><div class="index-ma">均线 ${ma(x)}</div><div class="index-ret"><span class="${cls(x.r20)}">20日 ${pct(x.r20)}</span><span class="${cls(x.r60)}">60日 ${pct(x.r60)}</span></div></button>`).join('');
  const nh=list.filter(x=>finite(x.near_high));
  const far=nh.filter(x=>x.near_high<=-.15).length,close=nh.filter(x=>x.near_high>-.05).length;
  const best=nh.slice().sort((a,b)=>b.near_high-a.near_high)[0];
  const picks=(weekly&&weekly.picks||[]).filter(p=>finite(p.near_high));
  const pickAvg=picks.length?picks.reduce((s,p)=>s+p.near_high,0)/picks.length:null;
  const N=nh.length;
  let lead=close===N?`${N}个宽基指数都在250日高点5%以内，普涨格局。`
    :far===N?`${N}个宽基指数全部距250日高点15%以上，整体处于调整期。`
    :close>=N-1&&far===0?`多数宽基接近高点（${close}/${N} 个在5%以内），整体偏强。`
    :far>=N-1&&close===0?`多数宽基离高点较远（${far}/${N} 个距高点15%以上），整体偏弱。`
    :close&&far?`宽基分化：${close} 个在高点5%以内，${far} 个距高点15%以上。`
    :`宽基处于中间状态：${close} 个在高点5%以内，${far} 个距高点15%以上。`;
  if(best)lead+=`宽基里离高点最近的是${escapeHTML(best.name)}（${best.near_high===0?'新高':pct(best.near_high)}）`;
  if(pickAvg!=null)lead+=`；周度清单5只平均距高点 ${pct(pickAvg)}${pickAvg-(best?best.near_high:0)>.03?'，强势集中在宽基之外的板块':''}。`;else lead+='。';
  box.innerHTML=`<p class="index-lead">${lead}</p><div class="index-grid">${cards}</div>`;
  box.querySelectorAll('.index-card').forEach(b=>b.addEventListener('click',()=>{const r=state.data.find(x=>x.ticker===b.dataset.code);if(r)openDrawer(r);}));
}
init();
