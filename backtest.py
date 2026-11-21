"""Walk-forward evaluation of the momentum model and its candidate changes.

    python backtest.py --fetch      # pull ~5 years of daily bars (batch endpoint, 10 per call), then evaluate
    python backtest.py              # re-evaluate from data_cache/backtest_klines.json
    python backtest.py --synthetic  # pipeline check on generated data (no network)

Writes reports/backtest.md and reports/backtest.json. Every config is scored with
model.score_panel and evaluated on the same set of names and dates, so differences come
from the model, not from the sample.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd

import model
import strategy
import radar
from universe import ASSET_CLASS, CLUSTERS, ETF_GROUPS, UNIVERSE_VERSION

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'data_cache/backtest_klines.json'
HORIZONS = (5, 20)
TOP_N = 10
MIN_NAMES = 20
EVAL_MIN_ADTV = 2e7  # evaluate on names that are tradeable in size (yuan/day)

V1 = model.V1
CONFIGS = [
    V1,
    model.PROD,
    V1.variant('v1 无加减分', trend_bonus=0, rs_bonus=0, overheat_penalty=0),
    V1.variant('v1 + 跳过近5日', skip_recent=5),
    V1.variant('v1 + 风险调整', risk_adjust=True),
    V1.variant('v1 + 连续过热扣分', overheat='linear'),
    V1.variant('v1 + 仅权益排名', rank_scope='equity'),
    V1.variant('v1 + 同类去重', dedupe=True),
    V1.variant('v1 + 3日平滑', smooth=3),
    V1.variant('v1 + 状态缓冲', hysteresis=True),
    model.V2,
]


# ---------------------------------------------------------------- data
def fetch(years=5):
    """Batch endpoint first (10 codes per call); if the key lacks permission for it,
    fall back to the single-ETF endpoint that production already uses."""
    key = radar.api_key()
    cutoff = radar.completed_cutoff()
    days = 365 * years - 2  # API window is at most 5 natural years
    start = dt.datetime.combine(cutoff - dt.timedelta(days=days), dt.time(), radar.TZ)
    end = dt.datetime.combine(cutoff, dt.time(23, 59, 59), radar.TZ)
    codes = [c for items in ETF_GROUPS.values() for c, _ in items]
    entries = {}
    batch = True
    for i in range(0, len(codes), 10):
        chunk = codes[i:i + 10]
        if batch:
            try:
                p = radar.api_get('/api/fund/market/historical-batch', dict(
                    thscodes=','.join(radar.thscode_of(c) for c in chunk), interval='1d',
                    start=int(start.timestamp() * 1000), end=int(end.timestamp() * 1000)), key)
            except radar.APIError as exc:
                if exc.code not in radar.AUTH_API_CODES:
                    raise
                print(f'批量接口不可用（业务码 {exc.code}），改用单只接口逐只获取', flush=True)
                batch = False
            else:
                groups = {g.get('thscode'): g.get('item') or [] for g in (p.get('data') or {}).get('item') or []}
                for c in chunk:
                    rows = radar.normalize(groups.get(radar.thscode_of(c), []), cutoff)
                    entries[c] = dict(rows=rows, source='同花顺金融API', adjustment='qfq')
                    print(f'{c} {len(rows)} bars', flush=True)
                time.sleep(.4)
                continue
        for c in chunk:
            try:
                rows = radar.request_history(c, key, days=days, min_bars=1)['rows']
            except radar.APIError as exc:
                if exc.code in radar.AUTH_API_CODES:
                    raise RuntimeError(f'单只接口也返回业务码 {exc.code}：key 无效或没有行情权限，请在同花顺 API Key 管理页检查。') from None
                raise
            except ValueError as exc:
                print(f'{c} 无数据：{exc}', flush=True)
                rows = []
            entries[c] = dict(rows=rows, source='同花顺金融API', adjustment='qfq')
            print(f'{c} {len(rows)} bars', flush=True)
            time.sleep(.4)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(dict(fetched_at=dt.datetime.now(radar.TZ).isoformat(timespec='seconds'),
                                     universe_version=UNIVERSE_VERSION, entries=entries), ensure_ascii=False))
    return entries


def synthetic(n=40, days=900, effect=1.0, seed=7):
    """Random walks whose drift is persistent, so momentum has a known positive edge.
    effect=0 gives pure noise (IC should be ~0)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range('2022-01-03', periods=days).strftime('%Y-%m-%d')
    codes = [radar.BENCHMARK] + [f'9{i:05d}' for i in range(1, n)]
    entries = {}
    for code in codes:
        drift = np.zeros(days)
        for t in range(1, days):
            drift[t] = .995 * drift[t - 1] + rng.normal(0, .00012)
        ret = effect * drift + rng.normal(0, .015, days)
        close = 2 * np.exp(np.cumsum(ret))
        spread = np.abs(rng.normal(0, .006, days)) * close
        rows = [dict(date=d, open=float(c), high=float(c + s), low=float(max(c - s, .01)), close=float(c),
                     volume=1e6, turnover=float(rng.uniform(3e7, 3e8))) for d, c, s in zip(dates, close, spread)]
        entries[code] = dict(rows=rows)
    asset = {c: 'equity' for c in codes}
    clusters = {'dup': codes[1:3]}
    return entries, asset, clusters


# ---------------------------------------------------------------- evaluation
def _rank_ic(scores, fwd):
    s, f = scores.rank(axis=1), fwd.where(scores.notna()).rank(axis=1)
    s = s.where(f.notna())
    sc, fc = s.sub(s.mean(axis=1), axis=0), f.sub(f.mean(axis=1), axis=0)
    den = np.sqrt((sc ** 2).sum(axis=1) * (fc ** 2).sum(axis=1))
    return ((sc * fc).sum(axis=1) / den.replace(0, np.nan)).where(s.notna().sum(axis=1) >= MIN_NAMES)


def _buckets(scores, fwd):
    """Per date: rank within names that have both a score and a forward return."""
    m = scores.notna() & fwd.notna()
    n = m.sum(axis=1)
    rank = scores.where(m).rank(axis=1, method='first')
    return m, n, rank


def _quintiles(scores, fwd):
    m, n, rank = _buckets(scores, fwd)
    q = np.floor((rank - 1).mul(5).div(n, axis=0))
    f = fwd.where(m)
    out = pd.DataFrame({f'Q{i + 1}': f.where(q == i).mean(axis=1) for i in range(5)})
    return out.where(n >= MIN_NAMES)


def _top(scores, fwd):
    m, n, rank = _buckets(scores, fwd)
    top = rank.gt(n - TOP_N, axis=0) & m
    f = fwd.where(m)
    excess = (f.where(top).mean(axis=1) - f.mean(axis=1)).where(n >= MIN_NAMES)
    valid = (n >= MIN_NAMES).to_numpy()
    t = top.to_numpy()
    keep = valid[1:] & valid[:-1]
    churn = 1 - (t[1:] & t[:-1]).sum(axis=1)[keep] / TOP_N
    return excess, (float(churn.mean()) if len(churn) else None)


def _tstat(series, step):
    x = series.dropna().iloc[::step]
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std(ddof=1) > 0 else None


def evaluate(entries, asset_class=ASSET_CLASS, clusters=CLUSTERS, benchmark=radar.BENCHMARK):
    panel = model.build_panel(entries, benchmark)
    close = panel['close']
    fwd = {k: close.shift(-k) / close - 1 for k in HORIZONS}
    equity = np.array([asset_class.get(t, 'equity') == 'equity' for t in close.columns])
    common = panel['eligible'] & equity & (panel['adtv20'] >= EVAL_MIN_ADTV)
    regime = model.regime(panel, asset_class)['state']
    years = pd.Series(pd.to_datetime(close.index).year, index=close.index)
    results = []
    for cfg in CONFIGS:
        out = model.score_panel(panel, cfg, asset_class, clusters)
        scores = out['score'].where(common)
        res = dict(name=cfg.name, config={k: v for k, v in cfg.__dict__.items() if k != 'name'})
        for k in HORIZONS:
            ic = _rank_ic(scores, fwd[k])
            qs = _quintiles(scores, fwd[k])
            spread = qs['Q5'] - qs['Q1']
            excess, churn = _top(scores, fwd[k])
            res[f'h{k}'] = dict(
                days=int(ic.notna().sum()), ic_mean=float(ic.mean()), ic_ir=float(ic.mean() / ic.std()) if ic.std() else None,
                ic_t=_tstat(ic, k), ic_positive=float((ic.dropna() > 0).mean()),
                quintiles={c: float(qs[c].mean()) for c in qs}, q5_q1=float(spread.mean()), q5_q1_t=_tstat(spread, k),
                top_excess=float(excess.mean()), top_excess_t=_tstat(excess, k), top_churn=churn,
                ic_by_year={int(y): float(v) for y, v in ic.groupby(years).mean().dropna().items()},
                ic_by_regime={s: float(v) for s, v in ic.groupby(regime).mean().dropna().items()},
                top_excess_by_regime={s: float(v) for s, v in excess.groupby(regime).mean().dropna().items()})
        # Do the labels separate future returns? Excess 20-day return vs the common set.
        setup = out['setup'].where(common)
        f20 = fwd[20].where(common)
        ex = f20.sub(f20.mean(axis=1), axis=0)
        res['setups'] = {s: dict(share=float((setup == s).sum().sum() / common.sum().sum()), excess20=float(ex.where(setup == s).stack().mean()))
                         for s in ('Momentum', 'Strong / wait pullback', 'Pullback watch', 'Avoid / broken')}
        strong = setup.isin(model.STRONG) & common
        res['strong_entries_per_day'] = float((strong & ~strong.shift(1, fill_value=False)).sum(axis=1).iloc[1:].mean())
        results.append(res)
    daily = close.pct_change().iloc[-250:]
    corr = daily.corr(min_periods=120)
    pairs = sorted(((a, b, float(corr.at[a, b])) for i, a in enumerate(corr.columns) for b in corr.columns[i + 1:]
                    if pd.notna(corr.at[a, b]) and corr.at[a, b] >= .9), key=lambda x: -x[2])
    cal = panel['calendar']
    rule = rule_backtest(panel, asset_class)
    valid = common.sum(axis=1) >= MIN_NAMES
    span = (valid[valid].index[0], valid[valid].index[-1]) if valid.any() else (None, None)
    return dict(generated=dt.datetime.now(radar.TZ).isoformat(timespec='seconds'), calendar=[cal[0], cal[-1]] if cal else None,
                eval_span=list(span), names=int(common.any().sum()), eval_min_adtv=EVAL_MIN_ADTV, top_n=TOP_N,
                regime_share={k: float(v) for k, v in regime[valid].value_counts(normalize=True).items()},
                configs=results, high_corr_pairs=pairs[:30], rule=rule)


def rule_backtest(panel, asset_class, start=None, random_runs=200, seed=0):
    """Portfolio-level test of strategy.py's weekly rule against the benchmark, the
    equal-weight candidate set and random 5-name picks from the same candidates."""
    cal = panel['calendar']
    nh = strategy.near_high(panel)
    have = nh.notna().sum(axis=1)
    first = next((d for d in cal if have.get(d, 0) >= MIN_NAMES), None)
    start = start or first
    if start is None:
        return None
    sim = strategy.simulate(panel, asset_class, start)
    if len(sim['returns']) < 60:
        return None
    years = pd.Series(pd.to_datetime(sim['returns'].index).year, index=sim['returns'].index)
    by = lambda r: {int(y): float(v) for y, v in ((1 + r).groupby(years).prod() - 1).items()}
    # Random picks: same candidates, same schedule and costs.
    rng = np.random.default_rng(seed)
    cand = strategy.candidates(panel, asset_class) & nh.notna()
    ret = panel['close'].pct_change().fillna(0.0).to_numpy()
    sched = set(strategy.week_ends(cal))
    idx = [i for i, d in enumerate(cal) if d >= sim['returns'].index[0] or (i + 1 < len(cal) and cal[i + 1] == sim['returns'].index[0])]
    i0, cm = idx[0], cand.to_numpy()
    rand = []
    for _ in range(random_runs):
        w = np.zeros(ret.shape[1]); out = []
        for i in range(i0, len(cal) - 1):
            c = 0.0
            if cal[i] in sched:
                pool = np.nonzero(cm[i])[0]
                new = np.zeros_like(w)
                if len(pool):
                    new[rng.choice(pool, size=min(strategy.TOP_N, len(pool)), replace=False)] = 1 / min(strategy.TOP_N, len(pool))
                c = np.abs(new - w).sum() * strategy.COST; w = new
            out.append((w * ret[i + 1]).sum() - c)
            g = w * (1 + ret[i + 1]); w = g / g.sum() if g.sum() > 0 else g
        rand.append(strategy.stats(pd.Series(out))['cagr'])
    rand = np.array([r for r in rand if r is not None])
    st = strategy.stats(sim['returns'])
    return dict(start=sim['returns'].index[0], end=sim['returns'].index[-1], rule=strategy.RULE_VERSION, cost=strategy.COST,
                strategy=st, benchmark=strategy.stats(sim['benchmark']), equal_weight=strategy.stats(sim['equal_weight']),
                turnover=float(sim['turnover'] / (len(sim['returns']) / 252)),
                by_year=dict(strategy=by(sim['returns']), benchmark=by(sim['benchmark']), equal_weight=by(sim['equal_weight'])),
                random=dict(runs=int(len(rand)), median=float(np.median(rand)), p95=float(np.percentile(rand, 95)),
                            beaten=float((rand < st['cagr']).mean())) if len(rand) and st['cagr'] is not None else None)


# ---------------------------------------------------------------- report
def _p(v, digits=2):
    return '—' if v is None or (isinstance(v, float) and not math.isfinite(v)) else f'{v * 100:+.{digits}f}%'


def _f(v, digits=3):
    return '—' if v is None or (isinstance(v, float) and not math.isfinite(v)) else f'{v:+.{digits}f}'


def verdict(base, cand):
    """Adopt only if 20-day IC, Q5-Q1 and top-10 excess all improve and IC is better in most years."""
    b, c = base['h20'], cand['h20']
    years = [y for y in c['ic_by_year'] if y in b['ic_by_year']]
    wins = sum(c['ic_by_year'][y] > b['ic_by_year'][y] for y in years)
    better = c['ic_mean'] > b['ic_mean'] and c['q5_q1'] > b['q5_q1'] and c['top_excess'] > b['top_excess']
    if better and years and wins / len(years) >= .6:
        return f'改善（{wins}/{len(years)} 年 IC 更高）'
    if c['ic_mean'] < b['ic_mean'] and c['q5_q1'] < b['q5_q1']:
        return '变差'
    return f'不明确（{wins}/{len(years)} 年 IC 更高）'


def report(res, label='同花顺前复权日线'):
    base = res['configs'][0]
    L = ['# 动量模型回测报告', '',
         f'- 数据：{label}，日历 {res["calendar"][0]} ~ {res["calendar"][1]}；评估区间 {res["eval_span"][0]} ~ {res["eval_span"][1]}',
         f'- 评估样本：权益类、满足121日对齐、20日均成交额 ≥ {res["eval_min_adtv"] / 1e8:.1f} 亿元，共 {res["names"]} 只；所有方案用同一样本',
         '- 市场状态占比：' + '，'.join(f'{k} {v:.0%}' for k, v in res['regime_share'].items()),
         f'- 生成时间：{res["generated"]}', '',
         '## 1. 方案对比（20日前瞻）', '',
         '| 方案 | Rank IC | IC t值 | IC>0 天数 | Q5−Q1 | 前10超额 | 前10日换手 | 结论 |', '|---|---|---|---|---|---|---|---|']
    for c in res['configs']:
        h = c['h20']
        L.append(f'| {c["name"]} | {_f(h["ic_mean"])} | {_f(h["ic_t"], 2)} | {h["ic_positive"]:.0%} | {_p(h["q5_q1"])} | {_p(h["top_excess"])} | {_p(h["top_churn"], 0) if h["top_churn"] is not None else "—"} | {"基准" if c is base else verdict(base, c)} |')
    L += ['', '## 2. 5日前瞻', '', '| 方案 | Rank IC | IC t值 | Q5−Q1 | 前10超额 |', '|---|---|---|---|---|']
    for c in res['configs']:
        h = c['h5']
        L.append(f'| {c["name"]} | {_f(h["ic_mean"])} | {_f(h["ic_t"], 2)} | {_p(h["q5_q1"])} | {_p(h["top_excess"])} |')
    years = sorted({y for c in res['configs'] for y in c['h20']['ic_by_year']})
    L += ['', '## 3. 分年度 20日 Rank IC', '', '| 方案 | ' + ' | '.join(map(str, years)) + ' |', '|---|' + '---|' * len(years)]
    for c in res['configs']:
        L.append(f'| {c["name"]} | ' + ' | '.join(_f(c['h20']['ic_by_year'].get(y)) for y in years) + ' |')
    states = ['risk_on', 'neutral', 'risk_off']
    L += ['', '## 4. 分市场状态（20日）', '', '| 方案 | ' + ' | '.join(f'{s} IC' for s in states) + ' | ' + ' | '.join(f'{s} 前10超额' for s in states) + ' |', '|---|' + '---|' * 6]
    for c in res['configs']:
        h = c['h20']
        L.append(f'| {c["name"]} | ' + ' | '.join(_f(h['ic_by_regime'].get(s)) for s in states) + ' | ' + ' | '.join(_p(h['top_excess_by_regime'].get(s)) for s in states) + ' |')
    L += ['', '## 5. 状态标签是否有区分度（20日超额，相对同日样本均值）', '', '| 方案 | 动量成立 | 强势·等回踩 | 等待确认 | 趋势破坏 | 每日新进强势 |', '|---|---|---|---|---|---|']
    for c in res['configs']:
        s = c['setups']
        L.append(f'| {c["name"]} | ' + ' | '.join(f'{_p(s[k]["excess20"])}（{s[k]["share"]:.0%}）' for k in ('Momentum', 'Strong / wait pullback', 'Pullback watch', 'Avoid / broken')) + f' | {c["strong_entries_per_day"]:.2f} |')
    rule = res.get('rule')
    if rule:
        L += ['', f'## 6. 周度清单规则（{rule["rule"]}，{rule["start"]} ~ {rule["end"]}，单边成本{rule["cost"]:.1%}）', '',
              '| | 年化 | 年化波动 | 夏普 | 最大回撤 |', '|---|---|---|---|---|']
        for name, k in (('周度清单（距250日高点前5）', 'strategy'), ('沪深300ETF', 'benchmark'), ('权益ETF等权', 'equal_weight')):
            x = rule[k]
            L.append(f'| {name} | {_p(x["cagr"], 1)} | {_p(x["vol"], 1).lstrip("+")} | {_f(x["sharpe"], 2)} | {_p(x["mdd"], 1)} |')
        ys = sorted(rule['by_year']['strategy'])
        L += ['', '| 年份 | ' + ' | '.join(map(str, ys)) + ' |', '|---|' + '---|' * len(ys)]
        for name, k in (('周度清单', 'strategy'), ('沪深300ETF', 'benchmark'), ('等权', 'equal_weight')):
            L.append(f'| {name} | ' + ' | '.join(_p(rule['by_year'][k].get(y), 1) for y in ys) + ' |')
        rnd = rule.get('random')
        L += ['', f'- 年换手约 {rule["turnover"]:.0f} 倍。'] + ([f'- 同一候选池随机选5只、同样每周调仓和成本，{rnd["runs"]} 次模拟：年化中位数 {_p(rnd["median"], 1)}，95分位 {_p(rnd["p95"], 1)}；本规则超过 {rnd["beaten"]:.0%} 的随机组合。随机组合几乎每周全换，成本拖累比本规则大，这一项只作参考。'] if rnd else [])
        L += ['- 规则在 2026-11-21 根据本数据选定，样本内结果偏乐观；以页面上自 2026-11-20 起的纸面跟踪为准。']
    L += ['', '## 7. 近250日日收益相关性 ≥ 0.90 的组合（用于核对 universe.CLUSTERS）', '']
    L += [f'- {a} / {b}：{r:.3f}' for a, b, r in res['high_corr_pairs']] or ['- 无']
    L += ['', '## 怎么读', '',
          '- **Rank IC**：当日评分排名与之后20日收益排名的相关系数。A股行业动量通常在 0.02–0.08 之间，t值 > 2 才算显著。',
          '- **t值**按不重叠窗口计算（20日每20天取一个点），避免重叠收益夸大显著性。',
          '- **Q5−Q1**：评分最高一档减最低一档的平均20日收益。**前10超额**：前10名平均收益减样本均值。',
          '- **结论**：20日 IC、Q5−Q1、前10超额同时变好，且至少60%年份 IC 更高，才算“改善”。',
          '', '## 局限', '',
          '- 观察池是今天挑选的，含事后选择偏差；新上市ETF满121日后才进入样本。',
          '- 前复权价格只用于计算收益，不影响结论；未计交易成本、冲击成本和跨境ETF溢价变化。',
          '- 5年只覆盖少数几轮牛熊，分年度和分状态结果的样本更小，需结合判断。', '']
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--years', type=int, default=5)
    ap.add_argument('--synthetic', action='store_true')
    args = ap.parse_args()
    if args.synthetic:
        entries, asset, clusters = synthetic()
        res = evaluate(entries, asset, clusters)
        label = '合成数据（仅用于检查流程，不代表真实市场）'
    else:
        entries = fetch(args.years) if args.fetch else json.loads(CACHE.read_text())['entries']
        res = evaluate(entries)
        label = '同花顺前复权日线'
    out = ROOT / 'reports'
    out.mkdir(exist_ok=True)
    suffix = '_synthetic' if args.synthetic else ''
    (out / f'backtest{suffix}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, allow_nan=False, default=str))
    (out / f'backtest{suffix}.md').write_text(report(res, label))
    print((out / f'backtest{suffix}.md').read_text())


if __name__ == '__main__':
    main()
