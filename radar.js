const state = {
  data: [],
  filtered: [],
  sortKey: 'score',
  sortDir: -1,
  selected: null,
  setup: 'all',
  group: 'all',
  query: '',
  watchOnly: false,
  favorites: [],
};
const $ = s => document.querySelector(s);
const svgNS = 'http://www.w3.org/2000/svg';
const setupNames = {
  Momentum: '动量成立',
  'Strong / wait pullback': '加速强势',
  'Pullback watch': '等待确认',
  'Avoid / broken': '趋势破坏',
  'Absolute up': '绝对动量成立',
  'Absolute down': '绝对动量不成立',
};

// Chinese display labels describe each fund; not official legal names.
const payload = JSON.parse(document.getElementById('dataset').textContent);
const etfNames = Object.fromEntries(payload.rows.map(r => [r.ticker, r.name]));
const etfName = ticker => escapeHTML(etfNames[ticker] || ticker);
const finite = v => typeof v === 'number' && Number.isFinite(v);
const pct = v => (finite(v) ? `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%` : '—');
const price = v =>
  finite(v) ? v.toLocaleString('zh-CN', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) : '—';
const cls = v => (finite(v) ? (v >= 0 ? 'positive' : 'negative') : '');
const scoreText = v => (finite(v) ? v.toFixed(1) : '—');
const statusClass = s =>
  s === 'Momentum' || s === 'Strong / wait pullback'
    ? 'momentum'
    : s === 'Pullback watch' || s === 'Absolute up'
      ? 'wait'
      : 'avoid';
const escapeHTML = s =>
  String(s ?? '').replace(
    /[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
setupNames['Data unavailable'] = '数据不足 / 日期不齐';
let previousFocus = null;

function renderKPIs() {
  // Breadth = domestic equity ETFs only (no bonds, commodities, HK or overseas).
  const d = state.data.filter(x => x.eligible && x.asset_class === 'equity' && x.market === '境内'),
    n = d.length;
  const complete = state.data.filter(x => x.eligible).length;
  const cards = [
    ['扫描范围', state.data.length, '只 ETF', `${complete} 只满足完整窗口 · 宽度按 A股权益 ${n} 只`],
    [
      '20日上涨',
      d.filter(x => x.r20 > 0).length,
      `/ ${n}`,
      `${Math.round((d.filter(x => x.r20 > 0).length / Math.max(n, 1)) * 100)}% 短线宽度`,
    ],
    [
      '60日上涨',
      d.filter(x => x.r60 > 0).length,
      `/ ${n}`,
      `${Math.round((d.filter(x => x.r60 > 0).length / Math.max(n, 1)) * 100)}% 中期宽度`,
    ],
    ['多头排列', d.filter(x => x.trend_aligned === true).length, `/ ${n}`, 'Close > 20EMA > 50MA > 120MA'],
  ];
  $('#kpiGrid').innerHTML = cards
    .map(
      c =>
        `<article class="kpi-card"><p class="kpi-label">${c[0]}</p><div class="kpi-value">${c[1]} <small>${c[2]}</small></div><p class="kpi-foot">${c[3]}</p></article>`,
    )
    .join('');
  const periods = [20, 60, 120];
  $('#breadthBars').innerHTML = periods
    .map(p => {
      const v = (d.filter(x => x[`r${p}`] > 0).length / Math.max(n, 1)) * 100;
      return `<div class="breadth-item"><span>${p}D</span><div class="breadth-track"><div class="breadth-fill" style="width:${v}%"></div></div><b>${Math.round(v)}%</b></div>`;
    })
    .join('');
  const breadth = periods.map(p => (n ? d.filter(x => x[`r${p}`] > 0).length / n : 0));
  const [title, copy] = marketRegime(breadth, n);
  $('#regimeTitle').textContent = title;
  $('#regimeCopy').textContent = copy;
}

function setupMatch(x) {
  if (state.setup === 'all') return true;
  if (state.setup === 'actionable') return x.setup === 'Momentum' || x.setup === 'Strong / wait pullback';
  if (state.setup === 'watch') return x.setup === 'Pullback watch';
  return x.setup === 'Avoid / broken' || x.setup === 'Data unavailable';
}
function applyFilters() {
  state.filtered = state.data.filter(
    x =>
      (!state.watchOnly || state.favorites.includes(x.ticker)) &&
      (state.group === 'all' || x.group === state.group) &&
      setupMatch(x) &&
      `${x.ticker} ${etfName(x.ticker)}`.toLowerCase().includes(state.query),
  );
  state.filtered.sort((a, b) => {
    const av = a[state.sortKey],
      bv = b[state.sortKey];
    if (!finite(av) && typeof av !== 'string') return 1;
    if (!finite(bv) && typeof bv !== 'string') return -1;
    return typeof av === 'number' ? (av - bv) * state.sortDir : String(av).localeCompare(String(bv)) * state.sortDir;
  });
  renderTable();
  renderScatter();
  renderSectors();
  savePreferences();
  document
    .querySelectorAll('th[data-sort]')
    .forEach(th =>
      th.setAttribute(
        'aria-sort',
        th.dataset.sort === state.sortKey ? (state.sortDir === 1 ? 'ascending' : 'descending') : 'none',
      ),
    );
  $('#watchOnly').setAttribute('aria-pressed', String(state.watchOnly));
}

function renderScatter() {
  const host = $('#scatterChart');
  host.innerHTML = '';
  const data = state.filtered.filter(x => x.eligible);
  const W = Math.max(320, host.clientWidth || 700),
    H = 340,
    m = { l: 48, r: 22, t: 18, b: 42 };
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  host.append(svg);
  if (!data.length) {
    svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#718096">没有符合条件的 ETF</text>`;
    return;
  }
  const xs = data.map(x => x.r60 * 100),
    ys = data.map(x => x.r20 * 100);
  let xmin = Math.min(-2, ...xs),
    xmax = Math.max(2, ...xs),
    ymin = Math.min(-2, ...ys),
    ymax = Math.max(2, ...ys);
  const xp = v => m.l + ((v - xmin) / (xmax - xmin)) * (W - m.l - m.r),
    yp = v => H - m.b - ((v - ymin) / (ymax - ymin)) * (H - m.t - m.b);
  for (let i = 0; i <= 5; i++) {
    const xv = xmin + ((xmax - xmin) * i) / 5,
      yv = ymin + ((ymax - ymin) * i) / 5;
    const vl = document.createElementNS(svgNS, 'line');
    vl.setAttribute('x1', xp(xv));
    vl.setAttribute('x2', xp(xv));
    vl.setAttribute('y1', m.t);
    vl.setAttribute('y2', H - m.b);
    vl.setAttribute('class', Math.abs(xv) < 0.01 ? 'zero-line' : 'grid-line');
    svg.append(vl);
    const ht = document.createElementNS(svgNS, 'text');
    ht.setAttribute('x', xp(xv));
    ht.setAttribute('y', H - 16);
    ht.setAttribute('text-anchor', 'middle');
    ht.setAttribute('class', 'axis-label');
    ht.textContent = `${xv.toFixed(0)}%`;
    svg.append(ht);
    const hl = document.createElementNS(svgNS, 'line');
    hl.setAttribute('x1', m.l);
    hl.setAttribute('x2', W - m.r);
    hl.setAttribute('y1', yp(yv));
    hl.setAttribute('y2', yp(yv));
    hl.setAttribute('class', Math.abs(yv) < 0.01 ? 'zero-line' : 'grid-line');
    svg.append(hl);
    const vt = document.createElementNS(svgNS, 'text');
    vt.setAttribute('x', m.l - 9);
    vt.setAttribute('y', yp(yv) + 4);
    vt.setAttribute('text-anchor', 'end');
    vt.setAttribute('class', 'axis-label');
    vt.textContent = `${yv.toFixed(0)}%`;
    svg.append(vt);
  }
  const xlab = document.createElementNS(svgNS, 'text');
  xlab.setAttribute('x', (m.l + W - m.r) / 2);
  xlab.setAttribute('y', H - 1);
  xlab.setAttribute('text-anchor', 'middle');
  xlab.setAttribute('class', 'axis-label');
  xlab.textContent = '60日收益';
  svg.append(xlab);
  [
    [xp(0), m.t, xp(0), H - m.b],
    [m.l, yp(0), W - m.r, yp(0)],
  ].forEach(coords => {
    const line = document.createElementNS(svgNS, 'line');
    ['x1', 'y1', 'x2', 'y2'].forEach((a, i) => line.setAttribute(a, coords[i]));
    line.setAttribute('class', 'zero-line');
    svg.append(line);
  });
  const sorted = [...data].sort((a, b) => a.adtv20 - b.adtv20),
    labels = new Set(
      [...data]
        .filter(x => finite(x.score))
        .sort((a, b) => b.score - a.score)
        .slice(0, W < 500 ? 4 : 10)
        .map(x => x.ticker),
    );
  sorted.forEach(x => {
    const t = Math.max(0, Math.min(1, (x.r120 + 0.15) / 0.7));
    const r = 5 + Math.max(0, Math.min(7, Math.log10(Math.max(x.adtv20 || 1e6, 1e6) / 1e6) * 1.3));
    const dot = document.createElementNS(svgNS, 'circle');
    dot.setAttribute('cx', xp(x.r60 * 100));
    dot.setAttribute('cy', yp(x.r20 * 100));
    dot.setAttribute('r', r);
    dot.setAttribute('fill', `hsl(${350 + t * 150} 70% 57%)`);
    dot.setAttribute('fill-opacity', '.78');
    dot.setAttribute('stroke', '#0d1420');
    dot.setAttribute('class', 'dot');
    dot.setAttribute('tabindex', '0');
    dot.setAttribute('role', 'button');
    dot.setAttribute('aria-label', `${x.ticker} ${etfName(x.ticker)} 评分 ${scoreText(x.score)}`);
    dot.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openDrawer(x);
      }
    });
    dot.addEventListener('click', () => openDrawer(x));
    dot.addEventListener('mouseenter', e => showTip(e, x));
    dot.addEventListener('mousemove', moveTip);
    dot.addEventListener('mouseleave', hideTip);
    svg.append(dot);
    if (labels.has(x.ticker)) {
      const lab = document.createElementNS(svgNS, 'text');
      lab.setAttribute('x', xp(x.r60 * 100) + r + 3);
      lab.setAttribute('y', yp(x.r20 * 100) - r + 2);
      lab.setAttribute('class', 'dot-label');
      lab.textContent = x.ticker;
      svg.append(lab);
    }
  });
}

function tableRow(x) {
  const fav = state.favorites.includes(x.ticker);
  const num = (v, extra = '') => `<td class="num ${extra}">${v}</td>`;
  const near = finite(x.near_high250) ? (x.near_high250 === 0 ? '新高' : pct(x.near_high250)) : '—';
  const cells = [
    `<td><button class="favorite" data-favorite="${x.ticker}" aria-label="${fav ? '取消收藏' : '收藏'}${x.ticker}"` +
      ` aria-pressed="${fav}">${fav ? '★' : '☆'}</button></td>`,
    `<td class="ticker-cell"><button type="button" class="ticker-link" aria-label="查看 ${x.ticker} ${etfName(x.ticker)} 详情">` +
      `<span class="ticker-code">${x.ticker}</span><span class="ticker-name">${etfName(x.ticker)}${premiumChip(x)}` +
      `${weeklySet.has(x.ticker) ? '<span class="pick-chip">周清单</span>' : ''}</span></button></td>`,
    `<td class="group-label">${escapeHTML(x.group)}</td>`,
    num(`¥${price(x.close)}`),
    ...['r20', 'r60', 'r120', 'rs60'].map(k => num(pct(x[k]), cls(x[k]))),
    num(`${finite(x.atr_pct) ? (x.atr_pct * 100).toFixed(1) : '—'}%`),
    num(near, x.near_high250 === 0 ? 'positive' : ''),
    num(scoreText(x.score), 'score-cell'),
    `<td class="rank-change">${rankChange(x.ticker)}</td>`,
    `<td><span class="table-chip ${statusClass(x.setup)}">${setupNames[x.setup]}</span></td>`,
  ];
  return `<tr data-code="${x.ticker}">${cells.join('')}</tr>`;
}
function renderTable() {
  $('#resultCount').textContent = `显示 ${state.filtered.length} / ${state.data.length} 只`;
  $('#tableBody').innerHTML = state.filtered.map(tableRow).join('');
  document.querySelectorAll('[data-favorite]').forEach(b =>
    b.addEventListener('click', e => {
      e.stopPropagation();
      const t = b.dataset.favorite;
      state.favorites = state.favorites.includes(t) ? state.favorites.filter(v => v !== t) : [...state.favorites, t];
      applyFilters();
    }),
  );
  if (!state.filtered.length)
    $('#tableBody').innerHTML =
      '<tr><td colspan="13" class="empty-note">没有符合条件的 ETF；可重置筛选或取消「仅看自选」。</td></tr>';
  document.querySelectorAll('#tableBody tr[data-code]').forEach(el => {
    el.addEventListener('click', () => openDrawer(state.data.find(x => x.ticker === el.dataset.code)));
  });
}

function openDrawer(x) {
  if (!x) return;
  previousFocus = document.activeElement;
  state.selected = x;
  const stats = [
    ['20日收益', pct(x.r20), cls(x.r20)],
    ['60日收益', pct(x.r60), cls(x.r60)],
    ['120日收益', pct(x.r120), cls(x.r120)],
    ['60日相对沪深300', pct(x.rs60), cls(x.rs60)],
    ['ATR / 价格', `${finite(x.atr_pct) ? (x.atr_pct * 100).toFixed(2) : '—'}%`, ''],
    ['距120日高点', pct(x.from_high120), cls(x.from_high120)],
  ].map(v => `<div class="detail-stat"><span>${v[0]}</span><b class="${v[2]}">${v[1]}</b></div>`);
  const zone = `<b>${price(x.pullback_low)}–${price(x.pullback_high)}</b>`;
  const steps = [
    x.setup === 'Strong / wait pullback'
      ? `距EMA20超过2.5倍ATR，处于加速段；回踩区 ${zone} 仅作参考，2022–2026年回测中此类状态之后未见系统性回落，追高波动也更大。`
      : `回踩观察区 ${zone}，观察是否止跌。`,
    `趋势延续的突破触发参考为 <b>${price(x.breakout_trigger)}</b>。`,
    `结构失效参考 <b>${price(x.stop_ref)}</b>；当前至该位置约 <b>${pct(x.stop_pct)}</b>。`,
  ].map((text, i) => `<div class="trade-step"><i>0${i + 1}</i><div>${text}</div></div>`);
  $('#drawerContent').innerHTML = [
    `<p class="section-kicker">ETF DETAIL</p><h2 class="detail-code">${x.ticker}</h2>`,
    `<p class="detail-meta">${etfName(x.ticker)}</p>`,
    `<p class="detail-meta">${escapeHTML(x.group)} · ${x.date || '无有效日期'} · ${x.cached ? '同源缓存' : '同花顺前复权日线'} · 收盘 ¥${price(x.close)}</p>`,
    `<div class="detail-score"><b>${scoreText(x.score)}</b><span>综合动量评分</span></div>`,
    `<div class="detail-grid">${stats.join('')}</div>`,
    premiumDetail(x),
    `<div class="trade-plan"><h3>${setupNames[x.setup]}</h3>${steps.join('')}</div>`,
    exposureDetail(x),
  ].join('');
  $('#detailDrawer').inert = false;
  $('#detailDrawer').classList.add('open');
  $('#drawerBackdrop').classList.add('open');
  $('#detailDrawer').setAttribute('aria-hidden', 'false');
  $('#drawerClose').focus();
}
function closeDrawer() {
  $('#detailDrawer').classList.remove('open');
  $('#drawerBackdrop').classList.remove('open');
  $('#detailDrawer').setAttribute('aria-hidden', 'true');
  $('#detailDrawer').inert = true;
  previousFocus?.focus();
}
function showTip(e, x) {
  $('#tooltip').innerHTML =
    `<b>${x.ticker}</b> · 评分 ${scoreText(x.score)}<br>20D ${pct(x.r20)} · 60D ${pct(x.r60)} · 120D ${pct(x.r120)}`;
  $('#tooltip').style.display = 'block';
  moveTip(e);
}
function moveTip(e) {
  $('#tooltip').style.left = `${Math.min(innerWidth - 230, e.clientX + 13)}px`;
  $('#tooltip').style.top = `${e.clientY + 13}px`;
}
function hideTip() {
  $('#tooltip').style.display = 'none';
}

function bind() {
  $('#watchOnly').addEventListener('click', () => {
    state.watchOnly = !state.watchOnly;
    applyFilters();
  });
  $('#resetFilters').addEventListener('click', () => {
    Object.assign(state, { query: '', group: 'all', setup: 'all', watchOnly: false, sortKey: 'score', sortDir: -1 });
    syncControls();
    applyFilters();
  });
  $('#searchInput').addEventListener('input', e => {
    state.query = e.target.value.trim().toLowerCase();
    applyFilters();
  });
  $('#groupSelect').addEventListener('change', e => {
    state.group = e.target.value;
    applyFilters();
  });
  document.querySelectorAll('#setupFilter button').forEach(b =>
    b.addEventListener('click', () => {
      document.querySelectorAll('#setupFilter button').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      state.setup = b.dataset.setup;
      syncControls();
      applyFilters();
    }),
  );
  document.querySelectorAll('th[data-sort]').forEach(th =>
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      state.sortDir = state.sortKey === key ? -state.sortDir : ['ticker', 'group', 'setup'].includes(key) ? 1 : -1;
      state.sortKey = key;
      applyFilters();
    }),
  );
  $('#drawerClose').addEventListener('click', closeDrawer);
  $('#drawerBackdrop').addEventListener('click', closeDrawer);
  addEventListener('keydown', e => {
    if (e.key === 'Escape') closeDrawer();
    if (e.key === 'Tab' && $('#detailDrawer').classList.contains('open')) trapFocus(e);
  });
  let timer;
  addEventListener('resize', () => {
    clearTimeout(timer);
    timer = setTimeout(renderScatter, 120);
  });
}

function renderSectors() {
  const groups = [...new Set(state.data.map(x => x.group))]
    .map(group => {
      const all = state.data.filter(x => x.group === group),
        d = all.filter(x => x.eligible),
        avg = k => {
          const v = d.map(r => r[k]).filter(finite);
          return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
        };
      return {
        group,
        count: d.length,
        total: all.length,
        score: avg('score'),
        returns: [20, 60, 120].map(n => avg(`r${n}`)),
        aligned: d.filter(r => r.trend_aligned).length,
      };
    })
    .sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity));
  const scored = groups.filter(g => finite(g.score)),
    others = groups.filter(g => !finite(g.score));
  const compact = !state.sectorsExpanded && scored.length > 8;
  const shown = compact ? [...scored.slice(0, 5), ...scored.slice(-3), ...others] : groups;
  const toggle =
    scored.length > 8
      ? `<button type="button" class="heat-toggle" id="sectorToggle">${compact ? `展开全部 ${groups.length} 组` : '收起'}</button>`
      : '';
  $('#sectorGrid').innerHTML =
    '<div class="heat-row heat-head"><span>板块 / 动量分</span><span>20日</span><span>60日</span><span>120日</span><span>多头 / 有效</span></div>' +
    shown
      .map(
        g =>
          `<button type="button" class="heat-row" data-group="${escapeHTML(g.group)}"><span><b>${escapeHTML(g.group)}</b><small>评分 ${scoreText(g.score)} · ${g.count}/${g.total} 有效</small></span>${g.returns.map(v => `<span class="heat-cell ${cls(v)}">${pct(v)}</span>`).join('')}<span>${g.aligned}/${g.count}<small>${g.count ? Math.round((g.aligned / g.count) * 100) : 0}% 多头</small></span></button>`,
      )
      .join('') +
    toggle;
  const tg = $('#sectorToggle');
  if (tg)
    tg.addEventListener('click', () => {
      state.sectorsExpanded = !state.sectorsExpanded;
      renderSectors();
    });
  document.querySelectorAll('[data-group]').forEach(b =>
    b.addEventListener('click', () => {
      state.group = b.dataset.group;
      syncControls();
      applyFilters();
      $('.table-section').scrollIntoView({ behavior: 'smooth' });
    }),
  );
}
function marketRegime([b20, b60, b120], n) {
  if (!n) return ['暂无有效样本', '完整窗口不足，暂不判断市场强弱。'];
  if (Math.max(b20, b60, b120) < 0.4)
    return ['多数样本下跌，强势集中于少数方向', '三个周期上涨比例均低于40%；周期表现一致，但不代表整体强势。'];
  if (b120 > 0.65 && b20 < 0.4) return ['长趋势仍在，短线动量收缩', '多数样本保留120日涨幅，但短线参与度不足。'];
  if (b20 > 0.6 && b60 > 0.6) return ['短中期动量扩散', '20日与60日上涨比例均超过60%，上涨参与度较高。'];
  if (b20 > 0.6 && b60 < 0.4) return ['短线回升，中期仍弱', '短线参与度改善，中期趋势尚未同步恢复。'];
  return ['结构分化，等待趋势确认', '各周期参与度尚未形成一致强势，结合板块与趋势状态观察。'];
}
function savePreferences() {
  try {
    localStorage.setItem(
      'jade-preferences-v1',
      JSON.stringify(
        Object.fromEntries(
          ['query', 'group', 'setup', 'sortKey', 'sortDir', 'watchOnly', 'favorites'].map(k => [k, state[k]]),
        ),
      ),
    );
  } catch {}
}
function restorePreferences() {
  try {
    const p = JSON.parse(localStorage.getItem('jade-preferences-v1') || '{}');
    if (typeof p.query === 'string') state.query = p.query;
    if (['all', ...state.data.map(x => x.group)].includes(p.group)) state.group = p.group;
    if (['all', 'actionable', 'watch', 'avoid'].includes(p.setup)) state.setup = p.setup;
    if ([...document.querySelectorAll('th[data-sort]')].some(x => x.dataset.sort === p.sortKey))
      state.sortKey = p.sortKey;
    if ([1, -1].includes(p.sortDir)) state.sortDir = p.sortDir;
    state.watchOnly = p.watchOnly === true;
    state.favorites = Array.isArray(p.favorites) ? p.favorites.filter(t => state.data.some(x => x.ticker === t)) : [];
  } catch {}
  syncControls();
}
function syncControls() {
  $('#searchInput').value = state.query;
  $('#groupSelect').value = state.group;
  document.querySelectorAll('#setupFilter button').forEach(b => {
    b.classList.toggle('active', b.dataset.setup === state.setup);
    b.setAttribute('aria-pressed', String(b.dataset.setup === state.setup));
  });
}
function rankChange(ticker) {
  const change = payload.comparison?.changes?.[ticker];
  return change
    ? change.rank_delta > 0
      ? `↑ ${change.rank_delta}`
      : change.rank_delta < 0
        ? `↓ ${-change.rank_delta}`
        : '—'
    : '暂无';
}
function renderChanges() {
  const c = payload.comparison;
  $('#comparisonDate').textContent = c?.asof ? `对比 ${c.asof}` : '暂无对照';
  if (!c?.changes) {
    $('#dailyChanges').innerHTML =
      '<p class="empty-note">暂无同口径的较早快照。模型、数据源、观察池版本变化，或两天都有新鲜评分的ETF不足90%时暂停比较；不推算历史排名。</p>';
    return;
  }
  const items = Object.entries(c.changes),
    names = list =>
      list.length
        ? list
            .slice(0, 5)
            .map(([t]) => `${etfName(t)} ${t}`)
            .join('、')
        : '无';
  const rises = items.filter(([, v]) => v.rank_delta > 0).sort((a, b) => b[1].rank_delta - a[1].rank_delta);
  $('#dailyChanges').innerHTML =
    [
      [
        '排名上升',
        rises.length
          ? rises
              .slice(0, 3)
              .map(([t, v]) => `${etfName(t)} ↑${v.rank_delta}`)
              .join('、')
          : '无',
      ],
      ['新进入强势', names(items.filter(([, v]) => v.entered_strong))],
      ['新转为趋势破坏', names(items.filter(([, v]) => v.broken))],
    ]
      .map(([title, text]) => `<article><span>${title}</span><p>${text}</p></article>`)
      .join('') +
    (c.excluded?.length
      ? `<p class="empty-note">${c.excluded.length} 只两天未都有新鲜评分，不参与比较：${escapeHTML(c.excluded.map(t => `${etfNames[t] || t} ${t}`).join('、'))}。名次在其余 ${items.length} 只中计算。</p>`
      : '');
}
// The page can be opened long after it was built; check freshness against today's date.
function bjNow() {
  const t = new Date(Date.now() + 8 * 3600e3).toISOString();
  return { date: t.slice(0, 10), time: t.slice(11, 16) };
}
function addDays(d, n) {
  const t = new Date(d + 'T00:00:00Z');
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
}
function staleness(p, now = bjNow()) {
  const cal = p.calendar;
  if (!cal || !p.asof) return null;
  const closed = new Set(cal.holidays),
    trading = d => {
      const w = new Date(d + 'T00:00:00Z').getUTCDay();
      return w > 0 && w < 6 && !closed.has(d);
    };
  // The daily run starts 19:00 Beijing time; allow until update_after before expecting today's bar.
  let expected = now.time >= (cal.update_after || '21:00') ? now.date : addDays(now.date, -1);
  while (!trading(expected)) expected = addDays(expected, -1);
  let lag = 0;
  for (let d = addDays(p.asof, 1); d <= expected && lag < 60; d = addDays(d, 1)) if (trading(d)) lag++;
  const unknown = [...new Set([now.date.slice(0, 4), p.asof.slice(0, 4)])].filter(y => !cal.known.includes(Number(y)));
  return { lag, expected, unknown };
}
function renderStaleness() {
  const s = staleness(payload),
    box = $('#staleBanner');
  if (!s || !box) return;
  if (s.lag < 1) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.innerHTML = `<b>数据可能已过期</b>：页面数据截止 ${escapeHTML(payload.asof)}，按交易日历此时应已更新到 ${escapeHTML(s.expected)}，落后 ${s.lag} 个交易日。自动更新可能失败或延迟，周度清单与评分均以页面数据日期为准。${s.unknown.length ? `（${escapeHTML(s.unknown.join('、'))}年休市安排未收录，仅按工作日估算）` : ''}`;
}
function init() {
  try {
    state.data = payload.rows;
    state.filtered = [...state.data];
    $('#asOf').textContent = `数据截止 ${payload.asof} · 同花顺日线`;
    const invalid = state.data.filter(x => !x.eligible).length,
      cached = state.data.filter(x => x.cached).length;
    $('#dataQuality').textContent =
      `${payload.offline ? '离线快照 · ' : ''}最近成功快照 ${payload.generated.replace('T', ' ').replace('+08:00', '')} 北京时间 · ${state.data.length - invalid}/${state.data.length} 只完整 · ${cached} 只缓存 · 基准 沪深300ETF（510300）`;
    if (invalid || cached || payload.asof < payload.requested_cutoff) $('#dataQuality').classList.add('warning');
    $('#healthSummary').textContent = `数据运行记录 · ${payload.errors.length} 条提醒`;
    $('#healthLog').innerHTML = payload.errors.length
      ? '<ul>' + payload.errors.map(e => `<li>${escapeHTML(e)}</li>`).join('') + '</ul>'
      : '<p>本次同花顺行情请求全部完成。' + (cached ? '存在缓存，请查看数据时间。' : '未使用缓存。') + '</p>';
    const groups = [...new Set(state.data.map(x => x.group))];
    $('#groupSelect').innerHTML += groups
      .map(g => `<option value="${escapeHTML(g)}">${escapeHTML(g)}</option>`)
      .join('');
    document.querySelectorAll('th[data-sort]').forEach(th => {
      th.innerHTML = `<button type="button" class="sort-btn">${th.innerHTML}</button>`;
    });
    restorePreferences();
    renderStaleness();
    renderWeekly();
    renderKPIs();
    renderRegimeState();
    renderChanges();
    bind();
    applyFilters();
  } catch (err) {
    document.querySelector('main').innerHTML =
      `<div class="error-state"><h2>数据载入失败</h2><p>${escapeHTML(err.message)}</p></div>`;
  }
}

const assetNames = { equity: '权益', commodity: '商品', bond: '债券', convertible: '可转债' };
const clusterMembers = Object.fromEntries(
  [...new Set(payload.rows.map(r => r.cluster).filter(Boolean))].map(c => [
    c,
    payload.rows.filter(r => r.cluster === c).map(r => r.ticker),
  ]),
);
function premiumChip(x) {
  if (!finite(x.premium) || Math.abs(x.premium) < 0.01) return '';
  return `<span class="premium-chip ${Math.abs(x.premium) >= 0.03 ? 'hot' : ''}" title="收盘价相对${escapeHTML(x.nav_date || '')}单位净值">${x.premium > 0 ? '溢价' : '折价'} ${(Math.abs(x.premium) * 100).toFixed(1)}%</span>`;
}
function premiumDetail(x) {
  if (!('premium' in x)) return '';
  if (!finite(x.premium)) return '<p class="detail-note">跨境ETF：本次未取得净值，溢价暂不显示。</p>';
  const warn =
    Math.abs(x.premium) >= 0.03 ? '溢价变化会直接影响场内收益，动量中可能含有溢价扩张成分。' : '溢折价处于常见范围。';
  return `<p class="detail-note">跨境ETF · 相对 ${escapeHTML(x.nav_date)} 单位净值 <b class="${x.premium >= 0.03 ? 'negative' : ''}">${x.premium > 0 ? '溢价' : '折价'} ${(Math.abs(x.premium) * 100).toFixed(2)}%</b>。${warn}</p>`;
}
function exposureDetail(x) {
  const lines = [];
  if (x.market && x.market !== '境内')
    lines.push(
      `${x.market === '港股' ? '港股' : '海外'}资产：场内价格以人民币计价，含汇率与溢价变化；不计入A股市场宽度。`,
    );
  if (x.added) lines.push(`${escapeHTML(x.added)} 起加入观察池，从这一天起才参与周度清单，纸面跟踪不会回溯计入。`);
  if (x.cluster)
    lines.push(
      `同类暴露「${escapeHTML(x.cluster)}」：${clusterMembers[x.cluster]
        .filter(t => t !== x.ticker)
        .map(t => `${etfName(t)} ${t}`)
        .join('、')}。近一年日收益相关性 ≥ 0.95，排名靠前时可能代表同一主题。`,
    );
  if (x.eligible && x.asset_class !== 'equity')
    lines.push(
      `${assetNames[x.asset_class]}类资产不与股票ETF一起排名，因此没有综合评分；绝对动量 <b>${x.abs_momentum ? '成立' : '不成立'}</b>（120日收益高于货币ETF同期收益，且收盘在120日均线上方）。`,
    );
  return lines.length
    ? `<div class="shadow-panel"><h3>暴露与资产类别</h3>${lines.map(l => `<p>${l}</p>`).join('')}</div>`
    : '';
}
function renderRegimeState() {
  const r = payload.regime;
  if (!r) return;
  const map = {
    risk_on: ['偏进攻', 'sector-up'],
    neutral: ['中性', 'sector-flat'],
    risk_off: ['偏防守', 'sector-down'],
  };
  const [label, klass] = map[r.state] || ['—', ''];
  $('#regimeState').innerHTML =
    `<span class="regime-chip ${r.state}">双动量状态 · ${label}</span><small>沪深300 120日 ${pct(r.bench_r120)} vs 现金 ${pct(r.hurdle)}（${escapeHTML(r.hurdle_source || '')}）· A股权益60日上涨占比 ${finite(r.breadth60) ? Math.round(r.breadth60 * 100) + '%' : '—'}</small><small class="regime-caveat">仅作背景：2022–2026回测中，按大盘趋势进出（如跌破200日线换国债）跑输一直持有沪深300，因此不作为买卖信号。</small>`;
  renderIndexStrip();
}
function trapFocus(e) {
  const items = [...$('#detailDrawer').querySelectorAll('button,[href],[tabindex]:not([tabindex="-1"])')].filter(
    el => !el.disabled,
  );
  if (!items.length) return;
  const first = items[0],
    last = items[items.length - 1];
  if (!$('#detailDrawer').contains(document.activeElement)) {
    e.preventDefault();
    first.focus();
  } else if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}
const weekly = payload.weekly;
const weeklySet = new Set(((weekly && weekly.picks) || []).map(p => p.ticker));
function navChart(nav) {
  const W = 520,
    H = 150,
    P = 8;
  const vals = nav.flatMap(p => [p.s, p.b, p.e]);
  const lo = Math.min(1, ...vals),
    hi = Math.max(1, ...vals);
  const x = i => P + (W - 2 * P) * (nav.length < 2 ? 1 : i / (nav.length - 1)),
    y = v => H - P - (H - 2 * P) * ((v - lo) / (hi - lo || 1));
  const line = k => nav.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`).join('');
  return `<svg class="track-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="纸面跟踪净值"><line x1="${P}" x2="${W - P}" y1="${y(1)}" y2="${y(1)}" class="base"/><path d="${line('e')}" class="ew"/><path d="${line('b')}" class="bench"/><path d="${line('s')}" class="strat"/></svg>`;
}
// Backtest figures come from reports/backtest.json (payload.backtest); never hard-code them here.
const pct1 = v => (finite(v) ? `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(1)}%` : '—');
function btText() {
  const b = payload.backtest;
  if (!b) return '回测结果见 reports/backtest.md。';
  let t = `${b.start.slice(0, 7)}至${b.end.slice(0, 7)}回测（次日开盘成交、单边${(b.cost * 100).toFixed(1)}%）年化${pct1(b.cagr)}、最大回撤${pct1(b.mdd)}，同期沪深300 ${pct1(b.bench_cagr)}、权益ETF等权 ${pct1(b.ew_cagr)}。`;
  if (b.grid_range)
    t += `参数稍变（跳过0–20日、前3–10名）时年化在${pct1(b.grid_range[0])}到${pct1(b.grid_range[1])}之间。`;
  const c = (b.costs || []).find(x => Math.abs(x.cost - 0.003) < 1e-9);
  if (c) t += `单边成本提高到0.3%时年化${pct1(c.cagr)}。`;
  if (b.subsample)
    t += `随机去掉30%的观察池，年化5–95分位为${pct1(b.subsample.cagr_p5)}～${pct1(b.subsample.cagr_p95)}。`;
  if (b.deflated)
    t += `按约${b.deflated.trials}次试验做多重检验校正后，真实优势成立的概率（DSR）约${Math.round(b.deflated.dsr * 100)}%。`;
  return t;
}
function trackPanel(tr) {
  const diff = tr.strategy.total - tr.benchmark.total;
  const verdict =
    diff >= 0
      ? `<span class="positive">跑赢沪深300 ${pct(diff)}</span>`
      : `<span class="negative">跑输沪深300 ${pct(-diff)}</span>`;
  const legend = [
    `<span class="strat">周度清单 ${pct(tr.strategy.total)}</span>`,
    `<span class="bench">沪深300ETF ${pct(tr.benchmark.total)}</span>`,
    `<span class="ew">权益ETF等权 ${pct(tr.equal_weight.total)}</span>`,
    tr.strategy.mdd != null ? `<span>清单最大回撤 ${pct(tr.strategy.mdd)}</span>` : '',
    tr.legacy ? `<span>原规则(不跳过)对照 ${pct(tr.legacy.total)}</span>` : '',
  ];
  const head =
    `<b>纸面跟踪 ${verdict}</b><span>自 ${escapeHTML(weekly.track_start)} 收盘信号起 · ${tr.weeks} 周 · 次日开盘成交` +
    ` · 已扣单边${(weekly.cost * 100).toFixed(1)}%成本</span>`;
  return `<div class="track"><div class="track-head">${head}</div>${navChart(tr.nav)}<div class="track-legend">${legend.join('')}</div></div>`;
}
function trackPending() {
  return (
    `<div class="track"><div class="track-head"><b>纸面跟踪</b><span>按 ${escapeHTML(weekly.track_start)} 收盘信号，` +
    `${escapeHTML(weekly.trade_date)} 开盘建仓后开始计入；次日开盘成交，单边成本0.1%。</span></div></div>`
  );
}
function pickCard(p, i) {
  const near = finite(p.near_high) ? (p.near_high > -0.0005 ? '处于新高' : '距高 ' + pct(p.near_high)) : '距高 —';
  return [
    `<button class="pick-card" data-code="${p.ticker}"><span class="pick-rank">${i + 1}</span>`,
    `<b>${etfName(p.ticker)}</b><small>${p.ticker}${weekly.buy.includes(p.ticker) ? ' · <em>新进</em>' : ''}</small>`,
    `<span class="pick-metric" title="排序依据：${weekly.skip}个交易日前的收盘价相对当时250日最高收盘价">`,
    `${p.signal > -0.0005 ? '5日前处于新高' : '5日前距高 ' + pct(p.signal)}</span>`,
    premiumChip(state.data.find(x => x.ticker === p.ticker) || {}),
    `<span class="pick-sub">当前${near} · 60日 ${pct(p.r60)}</span></button>`,
  ].join('');
}
function renderWeekly() {
  const bm = document.getElementById('btMethod');
  if (bm) bm.textContent = btText();
  const box = $('#weeklySection');
  if (!weekly) {
    box.innerHTML = '<p class="empty-note">历史数据不足250个交易日，本次没有周度清单。</p>';
    return;
  }
  const next = weekly.holding_from === 'next';
  const nm = t => `${etfName(t)}<small> ${t}</small>`;
  const title = next
    ? `下周清单 · ${escapeHTML(weekly.trade_date)} 开盘调仓`
    : `本周持有 · ${escapeHTML(weekly.trade_date)} 已开盘调仓`;
  const trades = `<div class="trade-lines">
    <div class="trade sell"><span>卖出</span><b>${weekly.sell.length ? weekly.sell.map(nm).join('、') : '无'}</b></div>
    <div class="trade buy"><span>买入</span><b>${weekly.buy.length ? weekly.buy.map(nm).join('、') : '无'}</b></div>
    <div class="trade hold"><span>继续持有</span><b>${weekly.hold.length ? weekly.hold.map(nm).join('、') : '无'}</b></div>
  </div><p class="weekly-note muted">${next ? `依据 ${escapeHTML(weekly.rebalance_date)} 收盘数据，${escapeHTML(weekly.trade_date)} 开盘按等权（各约20%）调整。` : `依据 ${escapeHTML(weekly.rebalance_date)} 收盘数据，已于 ${escapeHTML(weekly.trade_date)} 开盘调整。`}${weekly.previous_date ? '' : '首次建仓。'}</p>`;
  const cards = weekly.picks.map((p, i) => pickCard(p, i)).join('');
  const byCluster = {};
  weekly.picks.forEach(p => {
    const r = payload.rows.find(x => x.ticker === p.ticker);
    if (r && r.cluster) (byCluster[r.cluster] = byCluster[r.cluster] || []).push(p.ticker);
  });
  const conc = Object.entries(byCluster)
    .filter(([, v]) => v.length >= 2)
    .map(([k, v]) => `${v.length} 只属于同类暴露「${escapeHTML(k)}」`);
  const concNote = conc.length
    ? `<p class="weekly-note warn">集中度提示：清单中 ${conc.join('，')}，近一年日收益相关性 ≥ 0.95，实际接近押注同一主题，回撤可能更大。</p>`
    : '';
  const hot = weekly.picks
    .map(p => state.data.find(x => x.ticker === p.ticker))
    .filter(r => r && finite(r.premium) && r.premium >= 0.03);
  const premNote = hot.length
    ? `<p class="weekly-note warn">溢价提示：${hot.map(r => `${etfName(r.ticker)} 溢价 ${(r.premium * 100).toFixed(1)}%`).join('、')}（相对 ${escapeHTML(hot[0].nav_date || '最新')} 单位净值）。开盘按场内价买入要承担这部分溢价，溢价回落时即使标的指数不跌也会亏损。规则本身不按溢价过滤（缺少历史溢价数据，无法回测），请自行判断。</p>`
    : '';
  const prov = weekly.provisional
    ? `<p class="weekly-note">按今日收盘，下次调仓的前5：${weekly.provisional.map(p => etfName(p.ticker)).join('、')}（周五收盘后确定）</p>`
    : '';
  const tr = weekly.track;
  const track = tr ? trackPanel(tr) : trackPending();
  const lg = weekly.ledger;
  const ledgerNote = !lg
    ? ''
    : lg.source !== 'ledger'
      ? '<p class="weekly-note muted">本次没有可用的清单记录，纸面跟踪按当前数据重算。</p>'
      : `<p class="weekly-note muted">纸面跟踪按每周当时记录的清单计算（${lg.weeks} 周，记录只追加不修改，见仓库 track/ledger.json）。${lg.late.length ? `其中 ${lg.late.length} 周是在调仓日开盘后才补记的（${escapeHTML(lg.late.join('、'))}）。` : ''}</p>` +
        (lg.mismatches.length
          ? `<p class="weekly-note warn">按当前代码与数据重算，${lg.mismatches.length} 周的清单与当时记录不同（${escapeHTML(lg.mismatches.join('、'))}）；跟踪以当时记录为准。</p>`
          : '') +
        (lg.missing.length
          ? `<p class="weekly-note warn">记录中的 ${escapeHTML(lg.missing.join('、'))} 已不在观察池、没有价格，跟踪按剩余持仓等权计算。</p>`
          : '');
  box.innerHTML = `<div class="panel-head"><div><p class="section-kicker">WEEKLY PICKS · 250日高点轮动 v2</p><h2>${title}</h2></div><span class="badge">前${weekly.top_n}名 · 等权 · 每周一次</span></div>
  ${trades}<div class="pick-grid">${cards}</div>${concNote}${premNote}${prov}${track}${ledgerNote}
  <p class="weekly-note muted">规则：每周最后一个交易日收盘后，在权益类ETF中按“${weekly.skip}个交易日前距250日最高收盘价的距离”选前5只，下一交易日开盘等权调仓。${escapeHTML(btText())}应按+5%～+12%的保守预期看待。观察池为事后挑选，以纸面跟踪为准。仅为规则计算结果，不构成投资建议。</p>`;
  box
    .querySelectorAll('.pick-card')
    .forEach(b => b.addEventListener('click', () => openDrawer(state.data.find(x => x.ticker === b.dataset.code))));
}
function renderIndexStrip() {
  const box = $('#indexStrip'),
    list = (payload.regime && payload.regime.indices) || [];
  if (!list.length) {
    box.remove();
    return;
  }
  const trendName = { up: '多头排列', down: '空头排列', range: '震荡' },
    trendCls = { up: 'sector-up', down: 'sector-down', range: 'sector-flat' };
  const ma = x =>
    ['50', '120', '250']
      .map(
        k =>
          `<span class="ma ${x.above[k] ? 'on' : ''}" title="收盘${x.above[k] ? '高于' : '低于'}${k}日均线">${k}</span>`,
      )
      .join('');
  const cards = list
    .map(
      x =>
        `<button class="index-card" data-code="${x.ticker}"><div class="index-top"><b>${escapeHTML(x.name)}</b><span class="index-trend ${trendCls[x.trend]}">${trendName[x.trend]}</span></div><div class="index-near">${finite(x.near_high) ? (x.near_high === 0 ? '250日新高' : '距高点 ' + pct(x.near_high)) : '—'}</div><div class="index-ma">均线 ${ma(x)}</div><div class="index-ret"><span class="${cls(x.r20)}">20日 ${pct(x.r20)}</span><span class="${cls(x.r60)}">60日 ${pct(x.r60)}</span></div></button>`,
    )
    .join('');
  const nh = list.filter(x => finite(x.near_high));
  const far = nh.filter(x => x.near_high <= -0.15).length,
    close = nh.filter(x => x.near_high > -0.05).length;
  const best = nh.slice().sort((a, b) => b.near_high - a.near_high)[0];
  const picks = ((weekly && weekly.picks) || []).filter(p => finite(p.near_high));
  const pickAvg = picks.length ? picks.reduce((s, p) => s + p.near_high, 0) / picks.length : null;
  const N = nh.length;
  let lead =
    close === N
      ? `${N}个宽基指数都在250日高点5%以内，普涨格局。`
      : far === N
        ? `${N}个宽基指数全部距250日高点15%以上，整体处于调整期。`
        : close >= N - 1 && far === 0
          ? `多数宽基接近高点（${close}/${N} 个在5%以内），整体偏强。`
          : far >= N - 1 && close === 0
            ? `多数宽基离高点较远（${far}/${N} 个距高点15%以上），整体偏弱。`
            : close && far
              ? `宽基分化：${close} 个在高点5%以内，${far} 个距高点15%以上。`
              : `宽基处于中间状态：${close} 个在高点5%以内，${far} 个距高点15%以上。`;
  if (best)
    lead += `宽基里离高点最近的是${escapeHTML(best.name)}（${best.near_high === 0 ? '新高' : pct(best.near_high)}）`;
  if (pickAvg != null)
    lead += `；周度清单5只平均距高点 ${pct(pickAvg)}${pickAvg - (best ? best.near_high : 0) > 0.03 ? '，强势集中在宽基之外的板块' : ''}。`;
  else lead += '。';
  box.innerHTML = `<p class="index-lead">${lead}</p><div class="index-grid">${cards}</div>`;
  box.querySelectorAll('.index-card').forEach(b =>
    b.addEventListener('click', () => {
      const r = state.data.find(x => x.ticker === b.dataset.code);
      if (r) openDrawer(r);
    }),
  );
}
init();
