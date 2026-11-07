const state = { data: [], filtered: [], sortKey: 'score', sortDir: -1, selected: null, setup: 'all', group: 'all', query: '', watchOnly: false, favorites: [] };
const $ = (s) => document.querySelector(s);
const svgNS = 'http://www.w3.org/2000/svg';
const groupNames = { Broad:'宽基', Sector:'行业板块', Industry:'细分行业', RealAsset:'实物资产', Factor:'因子', Bond:'债券', International:'国际市场' };
const setupNames = { 'Momentum':'动量成立', 'Strong / wait pullback':'强势·等回踩', 'Pullback watch':'等待确认', 'Avoid / broken':'趋势破坏' };

// Chinese display labels describe each fund; not official legal names.
const payload=JSON.parse(document.getElementById('dataset').textContent);
const etfNames=Object.fromEntries(payload.rows.map(r=>[r.ticker,r.name]));
const etfName=ticker=>etfNames[ticker]||ticker;
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const pct=v=>finite(v)?`${v>=0?'+':''}${(v*100).toFixed(1)}%`:'—';
const price=v=>finite(v)?v.toLocaleString('zh-CN',{minimumFractionDigits:3,maximumFractionDigits:3}):'—';
const cls=v=>finite(v)?v>=0?'positive':'negative':'';
const scoreText=v=>finite(v)?v.toFixed(1):'—';
const statusClass=s=>s==='Momentum'?'momentum':(s.includes('wait')||s==='Pullback watch')?'wait':'avoid';
const escapeHTML=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
setupNames['Data unavailable']='数据不足 / 日期不齐';
let previousFocus=null;

function renderKPIs(){
  const d=state.data.filter(x=>x.eligible), n=d.length;
  const cards=[
    ['扫描范围',state.data.length,'只 ETF',`${n} 只满足完整窗口 · 同花顺日线`],
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
  const sorted=[...data].sort((a,b)=>a.adtv20-b.adtv20), labels=new Set([...data].sort((a,b)=>b.score-a.score).slice(0,W<500?4:10).map(x=>x.ticker));
  sorted.forEach(x=>{
    const t=Math.max(0,Math.min(1,(x.r120+.15)/.7)); const r=5+Math.max(0,Math.min(7,Math.log10(Math.max(x.adtv20||1e6,1e6)/1e6)*1.3));
    const dot=document.createElementNS(svgNS,'circle');dot.setAttribute('cx',xp(x.r60*100));dot.setAttribute('cy',yp(x.r20*100));dot.setAttribute('r',r);dot.setAttribute('fill',`hsl(${350+t*150} 70% 57%)`);dot.setAttribute('fill-opacity','.78');dot.setAttribute('stroke','#0d1420');dot.setAttribute('class','dot');dot.setAttribute('tabindex','0');
    dot.setAttribute('role','button');dot.setAttribute('aria-label',`${x.ticker} ${etfName(x.ticker)} 评分 ${scoreText(x.score)}`);dot.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openDrawer(x);}});dot.addEventListener('click',()=>openDrawer(x)); dot.addEventListener('mouseenter',e=>showTip(e,x));dot.addEventListener('mousemove',moveTip);dot.addEventListener('mouseleave',hideTip);svg.append(dot);
    if(labels.has(x.ticker)){const lab=document.createElementNS(svgNS,'text');lab.setAttribute('x',xp(x.r60*100)+r+3);lab.setAttribute('y',yp(x.r20*100)-r+2);lab.setAttribute('class','dot-label');lab.textContent=x.ticker;svg.append(lab);}
  });
}

function renderLeaders(){
  const top=state.filtered.filter(x=>x.eligible).sort((a,b)=>b.score-a.score).slice(0,10),max=Math.max(...top.map(x=>x.score),1);
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
  $('#tableBody').innerHTML=state.filtered.map(x=>`<tr data-code="${x.ticker}" tabindex="0" role="button" aria-label="查看${x.ticker}详情"><td><button class="favorite" data-favorite="${x.ticker}" aria-label="${state.favorites.includes(x.ticker)?'取消收藏':'收藏'}${x.ticker}" aria-pressed="${state.favorites.includes(x.ticker)}">${state.favorites.includes(x.ticker)?'★':'☆'}</button></td><td class="ticker-cell"><span class="ticker-code">${x.ticker}</span><span class="ticker-name">${etfName(x.ticker)}</span></td><td class="group-label">${groupNames[x.group]||x.group}</td><td class="num">¥${price(x.close)}</td><td class="num ${cls(x.r20)}">${pct(x.r20)}</td><td class="num ${cls(x.r60)}">${pct(x.r60)}</td><td class="num ${cls(x.r120)}">${pct(x.r120)}</td><td class="num ${cls(x.rs60)}">${pct(x.rs60)}</td><td class="num">${(finite(x.atr_pct)?(x.atr_pct*100).toFixed(1):'—')}%</td><td class="num score-cell">${scoreText(x.score)}</td><td class="rank-change">${rankChange(x.ticker)}</td><td><span class="table-chip ${statusClass(x.setup)}">${setupNames[x.setup]}</span></td></tr>`).join('');
  document.querySelectorAll('[data-favorite]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();const t=b.dataset.favorite;state.favorites=state.favorites.includes(t)?state.favorites.filter(v=>v!==t):[...state.favorites,t];applyFilters();}));
  if(!state.filtered.length)$('#tableBody').innerHTML='<tr><td colspan="12" class="empty-note">没有符合条件的 ETF；可重置筛选或取消「仅看自选」。</td></tr>';
  document.querySelectorAll('#tableBody tr[data-code]').forEach(el=>{const open=()=>openDrawer(state.data.find(x=>x.ticker===el.dataset.code));el.addEventListener('click',open);el.addEventListener('keydown',e=>{if(e.target===el&&e.key==='Enter')open();});});
}

function openDrawer(x){
  if(!x)return; previousFocus=document.activeElement;state.selected=x;
  $('#drawerContent').innerHTML=`<p class="section-kicker">ETF DETAIL</p><h2 class="detail-code">${x.ticker}</h2><p class="detail-meta">${etfName(x.ticker)}</p><p class="detail-meta">${groupNames[x.group]||x.group} · ${x.date||'无有效日期'} · ${x.cached?'同源缓存':'同花顺前复权日线'} · 收盘 ¥${price(x.close)}</p><div class="detail-score"><b>${scoreText(x.score)}</b><span>综合动量评分</span></div><div class="detail-grid">${[["20日收益",pct(x.r20),cls(x.r20)],["60日收益",pct(x.r60),cls(x.r60)],["120日收益",pct(x.r120),cls(x.r120)],["60日相对沪深300",pct(x.rs60),cls(x.rs60)],["ATR / 价格",`${(finite(x.atr_pct)?(x.atr_pct*100).toFixed(2):'—')}%`,''],["距120日高点",pct(x.from_high120),cls(x.from_high120)]].map(v=>`<div class="detail-stat"><span>${v[0]}</span><b class="${v[2]}">${v[1]}</b></div>`).join('')}</div><div class="trade-plan"><h3>${setupNames[x.setup]}</h3><div class="trade-step"><i>01</i><div>等待价格进入回踩观察区 <b>${price(x.pullback_low)}–${price(x.pullback_high)}</b>，观察是否止跌。</div></div><div class="trade-step"><i>02</i><div>趋势延续的突破触发参考为 <b>${price(x.breakout_trigger)}</b>。</div></div><div class="trade-step"><i>03</i><div>结构失效参考 <b>${price(x.stop_ref)}</b>；当前至该位置约 <b>${pct(x.stop_pct)}</b>。</div></div></div>`;
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
  $('#drawerClose').addEventListener('click',closeDrawer);$('#drawerBackdrop').addEventListener('click',closeDrawer);addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer();if(e.key==='Tab'&&$('#detailDrawer').classList.contains('open')){e.preventDefault();$('#drawerClose').focus();}});
  let timer;addEventListener('resize',()=>{clearTimeout(timer);timer=setTimeout(renderScatter,120);});
}

function renderSectors(){
 const groups=[...new Set(state.data.map(x=>x.group))].map(group=>{const all=state.data.filter(x=>x.group===group),d=all.filter(x=>x.eligible),avg=k=>d.length?d.reduce((s,r)=>s+r[k],0)/d.length:null;return {group,count:d.length,total:all.length,score:avg('score'),returns:[20,60,120].map(n=>avg(`r${n}`)),aligned:d.filter(r=>r.trend_aligned).length};}).sort((a,b)=>(b.score??-Infinity)-(a.score??-Infinity));
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
 const items=Object.entries(c.changes),names=list=>list.length?list.slice(0,5).map(([t])=>`${escapeHTML(etfName(t))} ${t}`).join('、'):'无';
 const rises=items.filter(([,v])=>v.rank_delta>0).sort((a,b)=>b[1].rank_delta-a[1].rank_delta);
 $('#dailyChanges').innerHTML=[['排名上升',rises.length?rises.slice(0,3).map(([t,v])=>`${escapeHTML(etfName(t))} ↑${v.rank_delta}`).join('、'):'无'],['新进入强势',names(items.filter(([,v])=>v.entered_strong))],['新转为趋势破坏',names(items.filter(([,v])=>v.broken))]].map(([title,text])=>`<article><span>${title}</span><p>${text}</p></article>`).join('');
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
  const groups=[...new Set(state.data.map(x=>x.group))];$('#groupSelect').innerHTML+=groups.map(g=>`<option value="${g}">${g}</option>`).join('');
  document.querySelectorAll('th[data-sort]').forEach(th=>{th.setAttribute('tabindex','0');th.setAttribute('role','button');th.addEventListener('keydown',e=>{if(e.key==='Enter')th.click();});});
  restorePreferences();renderKPIs();renderChanges();bind();applyFilters();
 }catch(err){document.querySelector('main').innerHTML=`<div class="error-state"><h2>数据载入失败</h2><p>${escapeHTML(err.message)}</p></div>`;}
}
init();
