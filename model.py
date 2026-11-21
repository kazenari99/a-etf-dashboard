"""Momentum model as point-in-time panels (dates x tickers).

Every indicator is causal (shift >= 0, rolling windows, ewm with adjust=False), so the
value at date t only uses bars up to t. That lets production read the last row and the
backtest read every row from one computation.

``V1`` reproduces the US ETF Momentum Radar exactly (tests/fixtures/us_model_parity.json)
and is the backtest baseline. ``PROD`` is what the A-share page publishes: V1 without the
overheat penalty (2021-2026 backtest: names > 2.5 ATR above EMA20 kept outperforming) and
with hysteresis on the strong label (halves label churn, score unchanged). V2 bundles the
other candidates; it did not beat V1 and is kept only as a backtest row.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

import numpy as np
import pandas as pd

WINDOW = 121  # sessions every ranked ETF must share with the benchmark
STRONG = ('Momentum', 'Strong / wait pullback')


@dataclass(frozen=True)
class ModelConfig:
    name: str = 'us-momentum-v1'
    weights: tuple = ((20, .30), (60, .40), (120, .30))
    skip_recent: int = 0        # drop the last k sessions from the 20-day horizon (A-share short-term reversal)
    risk_adjust: bool = False   # rank return / volatility of the same horizon instead of raw return
    overheat: str = 'step'      # 'step': -penalty beyond overheat_atr; 'linear': ramps over overheat_ramp
    overheat_atr: float = 2.5
    overheat_ramp: tuple = (1.5, 3.5)
    overheat_penalty: float = 8.0
    trend_bonus: float = 5.0
    rs_bonus: float = 3.0       # bonus for beating the benchmark over 60 days (a threshold, not a ranking)
    rank_scope: str = 'all'     # 'all' or 'equity' (commodities/bonds handled by absolute momentum)
    dedupe: bool = False        # one representative per exposure cluster sets the percentile scale
    min_adtv: float = 0.0       # yuan; below this an ETF is not ranked
    smooth: int = 1             # average score over the last n sessions
    hysteresis: bool = False    # once strong, stay strong until the looser pullback conditions fail

    def variant(self, name, **changes):
        return replace(self, name=name, **changes)


V1 = ModelConfig()
V2 = V1.variant('a-momentum-v2-candidate', skip_recent=5, risk_adjust=True, overheat='linear',
                rank_scope='equity', dedupe=True, min_adtv=2e7, smooth=3, hysteresis=True)
# v1.2: percentiles are computed among equity ETFs only; bonds, commodities and convertibles
# get no relative score (the page shows their absolute momentum instead).
PROD = V1.variant('a-momentum-v1.2', overheat_penalty=0.0, hysteresis=True, rank_scope='equity')
CASH_RATE = 0.015  # annual hurdle for absolute momentum (roughly short-term deposit/repo yield)


def _frame(rows):
    f = pd.DataFrame(rows)
    f.index = pd.Index(f['date'].astype(str), name='date')
    for key in ('open', 'high', 'low', 'close'):
        f[key] = f[key].astype(float)
    f['turnover'] = pd.to_numeric(f['turnover'], errors='coerce') if 'turnover' in f else np.nan
    return f


def indicator_frame(rows):
    """All per-ETF indicators on the ETF's own calendar."""
    f = _frame(rows)
    close, high, low = f['close'], f['high'], f['low']
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    out = pd.DataFrame(index=f.index)
    out['open'] = f['open']
    out['close'] = close
    out['atr14'] = tr.rolling(14).mean()
    out['ema20'] = close.ewm(span=20, adjust=False).mean()
    out['sma50'] = close.rolling(50).mean()
    out['sma120'] = close.rolling(120).mean()
    daily = close.pct_change()
    for n in (20, 60, 120):
        out[f'r{n}'] = close / close.shift(n) - 1
        out[f'vol{n}'] = daily.rolling(n).std() * math.sqrt(252)
    for k in (5,):
        out[f'r20s{k}'] = close.shift(k) / close.shift(20) - 1
    out['dist_ema_atr'] = (close - out['ema20']) / out['atr14'].where(out['atr14'] != 0)
    out['high20_prev'] = high.shift(1).rolling(20).max()
    out['low10'] = low.rolling(10).min()
    out['from_high120'] = close / high.rolling(120).max() - 1
    out['adtv20'] = f['turnover'].rolling(20).mean()
    out['trend_aligned'] = (close > out['ema20']) & (out['ema20'] > out['sma50']) & (out['sma50'] > out['sma120'])
    return out


def _aligned(own_dates, calendar):
    """True where the ETF's last WINDOW bars are exactly the calendar's last WINDOW sessions."""
    cal = np.asarray(calendar)
    own = np.asarray(sorted(own_dates))
    ok = np.zeros(len(cal), dtype=bool)
    present = np.isin(cal, own)
    run = pd.Series(present.astype(int)).rolling(WINDOW).sum().to_numpy()
    for i in np.nonzero(run == WINDOW)[0]:
        lo, hi = np.searchsorted(own, cal[i - WINDOW + 1], 'left'), np.searchsorted(own, cal[i], 'right')
        ok[i] = hi - lo == WINDOW  # no extra own sessions inside the window
    return ok


def build_panel(entries, benchmark):
    """Indicator panels on the benchmark calendar: {field: DataFrame(dates x tickers)}."""
    bench_rows = entries.get(benchmark, {}).get('rows') or []
    calendar = [r['date'] for r in bench_rows]
    tickers = list(entries)
    fields = {}
    eligible = {}
    for t in tickers:
        rows = entries[t].get('rows') or []
        if not rows or not calendar:
            eligible[t] = pd.Series(False, index=calendar)
            continue
        ind = indicator_frame(rows).reindex(calendar)
        for col in ind.columns:
            fields.setdefault(col, {})[t] = ind[col]
        ok = pd.Series(_aligned([r['date'] for r in rows], calendar), index=calendar)
        eligible[t] = ok & ind['dist_ema_atr'].notna()
    panel = {k: pd.DataFrame(v, index=calendar).reindex(columns=tickers) for k, v in fields.items()}
    panel['eligible'] = pd.DataFrame(eligible, index=calendar).reindex(columns=tickers).fillna(False).astype(bool)
    if 'trend_aligned' in panel:
        panel['trend_aligned'] = panel['trend_aligned'].astype('boolean').fillna(False).astype(bool)
    panel['calendar'] = calendar
    panel['benchmark'] = benchmark
    return panel


def pct_against(values, reference):
    """Average-rank percentile of each value within the row's reference values.

    With reference == values this equals DataFrame.rank(axis=1, pct=True). Non-reference
    values are placed on the reference scale, so duplicated exposures do not stretch it.
    """
    V, R = values.to_numpy(float), reference.to_numpy(float)
    out = np.full(V.shape, np.nan)
    for i in range(len(V)):
        ref = np.sort(R[i][~np.isnan(R[i])])
        m = ~np.isnan(V[i])
        if not len(ref) or not m.any():
            continue
        lo, hi = np.searchsorted(ref, V[i][m], 'left'), np.searchsorted(ref, V[i][m], 'right')
        out[i, m] = np.minimum((lo + (hi - lo + 1) / 2) / len(ref), 1.0)
    return pd.DataFrame(out, index=values.index, columns=values.columns)


def representatives(panel, eligible, clusters):
    """Per date, the most liquid eligible member of each cluster represents it."""
    rep = eligible.copy()
    adtv = panel['adtv20'].fillna(-np.inf).where(eligible, -np.inf)
    for members in clusters.values():
        cols = [c for c in members if c in rep.columns]
        if len(cols) < 2:
            continue
        best = adtv[cols].idxmax(axis=1)
        for c in cols:
            rep[c] = eligible[c] & (best == c)
    return rep


def _setups(panel, rs60, hysteresis):
    close, dist = panel['close'], panel['dist_ema_atr']
    r20, r60, r120 = panel['r20'], panel['r60'], panel['r120']
    strong = (r20 > 0) & (r60 > 0) & (r120 > 0) & panel['trend_aligned'] & (rs60 > 0)
    watch = (r60 > 0) & (r120 > 0) & (close > panel['sma50'])
    if hysteresis:
        s, w = strong.to_numpy(), watch.to_numpy()
        held = np.zeros_like(s)
        for i in range(len(s)):
            held[i] = s[i] | (w[i] & held[i - 1]) if i else s[i]
        strong = pd.DataFrame(held, index=strong.index, columns=strong.columns)
        watch = watch & ~strong
    labels = np.where(strong, np.where(dist <= 2.5, 'Momentum', 'Strong / wait pullback'),
                      np.where(watch, 'Pullback watch', 'Avoid / broken'))
    out = pd.DataFrame(labels, index=close.index, columns=close.columns)
    return out.where(panel['eligible'], 'Data unavailable')


def score_panel(panel, cfg, asset_class=None, clusters=None):
    """Return {'score', 'setup', 'ranked', 'rs60'} panels for one config."""
    asset_class = asset_class or {}
    eligible = panel['eligible']
    bench = panel['benchmark']
    ranked = eligible.copy()
    if cfg.rank_scope == 'equity':
        equity = pd.Series({t: asset_class.get(t, 'equity') == 'equity' for t in ranked.columns})
        ranked &= equity.reindex(ranked.columns).to_numpy()
    if cfg.min_adtv:
        ranked &= panel['adtv20'] >= cfg.min_adtv
    ref = representatives(panel, ranked, clusters or {}) if cfg.dedupe else ranked
    total = 0
    for n, w in cfg.weights:
        feat = panel[f'r{n}s{cfg.skip_recent}'] if (n == 20 and cfg.skip_recent) else panel[f'r{n}']
        if cfg.risk_adjust:
            feat = feat / panel[f'vol{n}'].where(panel[f'vol{n}'] > 0)
        if cfg.dedupe:
            pct = pct_against(feat.where(ranked), feat.where(ref))
        else:
            pct = feat.where(ranked).rank(axis=1, pct=True)
        total = total + w * pct
    score = total * 100
    rs60 = panel['r60'].sub(panel['r60'][bench], axis=0) if bench in panel['r60'] else panel['r60'] * np.nan
    score = score + np.where(panel['trend_aligned'], cfg.trend_bonus, 0)
    score = score + np.where(rs60 > 0, cfg.rs_bonus, 0)
    dist = panel['dist_ema_atr']
    if cfg.overheat == 'linear':
        lo, hi = cfg.overheat_ramp
        score = score - cfg.overheat_penalty * ((dist - lo) / (hi - lo)).clip(0, 1).fillna(0)
    else:
        score = score - np.where(dist > cfg.overheat_atr, cfg.overheat_penalty, 0)
    score = score.where(ranked)
    if cfg.smooth > 1:
        score = score.rolling(cfg.smooth, min_periods=1).mean().where(ranked)
    return dict(score=score, setup=_setups(panel, rs60, cfg.hysteresis), ranked=ranked, rs60=rs60)


def cash_hurdle(panel, cash=None, cash_rate=CASH_RATE):
    """120-day cash return per date: the money-market ETF's own return where available,
    otherwise the fixed annual rate."""
    fixed = (1 + cash_rate) ** (120 / 252) - 1
    idx = panel['close'].index
    if cash and cash in panel['r120'].columns:
        return panel['r120'][cash].reindex(idx).fillna(fixed)
    return pd.Series(fixed, index=idx)


def regime(panel, asset_class, cash_rate=CASH_RATE, market=None, cash=None):
    """Dual-momentum style market state per date: risk_on / neutral / risk_off.

    Absolute momentum: benchmark 120-day return against the cash hurdle and its 120-day
    average; breadth: share of eligible equity ETFs with a positive 60-day return
    (domestic equity only when `market` is given).
    """
    bench = panel['benchmark']
    hurdle = cash_hurdle(panel, cash, cash_rate)
    equity = [t for t in panel['eligible'].columns if asset_class.get(t, 'equity') == 'equity'
              and (market is None or market.get(t, '境内') == '境内')]
    elig = panel['eligible'][equity]
    breadth = (panel['r60'][equity] > 0).where(elig).sum(axis=1) / elig.sum(axis=1).replace(0, np.nan)
    above = panel['close'][bench] > panel['sma120'][bench]
    beats = panel['r120'][bench] > hurdle
    state = np.where(beats & above & (breadth >= .5), 'risk_on',
                     np.where(~beats & ~above & (breadth < .4), 'risk_off', 'neutral'))
    return pd.DataFrame({'state': state, 'breadth60': breadth, 'bench_r120': panel['r120'][bench],
                         'hurdle': hurdle}, index=panel['eligible'].index)


def absolute_momentum(panel, cash_rate=CASH_RATE, cash=None):
    hurdle = cash_hurdle(panel, cash, cash_rate)
    return panel['r120'].gt(hurdle, axis=0) & (panel['close'] > panel['sma120'])
