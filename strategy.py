"""Weekly rotation into equity ETFs that were near their 250-session closing high a week ago.

Rule v2 (frozen 2026-11-21; see docs in backtest-findings and README):
  * Signal: close 5 sessions ago / max(close over the 250 sessions up to then) - 1. The
    5-session skip ignores the latest breakout days: the unskipped v1 signal earned most of
    its backtest return in the first session after a new high, which cannot be captured by
    trading after the close (next open: +10.9%/yr; one-day-late signal: +4.5%/yr).
  * On the last trading session of each calendar week, rank equity ETFs (A-share, HK and
    overseas; not bonds/commodities/convertibles) with >= 2000万 yuan 20-day turnover by the
    signal; ties break on the 60-day return. Members added to the universe later only take
    part from their ADDED date.
  * Trade at the NEXT session's open into the top 5, equally weighted; 0.1% cost per side.
  * The paper track starts with the signal of TRACK_START (first trade at the next open).
    Its holdings come from the append-only ledger (ledger.py, track/ledger.json); returns
    are recomputed from prices on every run.

Backtest 2022-12..2026-11 with this execution: see reports/backtest.md (the single source
for the figures quoted in README and on the page). Nearby parameters ranged from about +2% to +20%, so treat the edge as uncertain.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

import trading_calendar
from universe import ADDED

LOOKBACK = 250
SKIP = 5
TOP_N = 5
MIN_ADTV = 2e7
COST = 0.001          # per side; ETF commission + spread, conservative
TRACK_START = '2026-11-20'   # first signal date; first trade at the next open (2026-11-23)
BENCHMARK = '510300'
RULE_VERSION = 'near-high-250-skip5-top5-weekly-v2'
LEGACY_RULE = 'near-high-250-top5-weekly-v1'


def near_high(panel):
    """Distance of today's close to the 250-session closing high (display; v1 signal)."""
    close = panel['close']
    return close / close.rolling(LOOKBACK, min_periods=LOOKBACK).max() - 1


def signal(panel, skip=SKIP):
    """v2 ranking signal: the near-high distance as it stood `skip` sessions ago."""
    return near_high(panel).shift(skip) if skip else near_high(panel)


def candidates(panel, asset_class, added=None):
    """Equity ETFs with enough turnover; members added later join from their ADDED date."""
    equity = np.array([asset_class.get(t, 'equity') == 'equity' for t in panel['close'].columns])
    ok = panel['eligible'] & equity & (panel['adtv20'] >= MIN_ADTV)
    added = ADDED if added is None else added
    if added:
        dates = pd.Series(ok.index, index=ok.index)
        for code, since in added.items():
            if code in ok.columns:
                ok[code] = ok[code] & (dates >= since)
    return ok


def week_ends(calendar, today_is_final=False):
    """Sessions that are the last trading day of their ISO week.

    The last calendar session counts only when the exchange calendar says the next
    trading day falls in a later week (e.g. a Friday, or a Thursday before a holiday)."""
    out = []
    for i, d in enumerate(calendar):
        day = dt.date.fromisoformat(d)
        if i + 1 < len(calendar):
            nxt = dt.date.fromisoformat(calendar[i + 1])
        else:
            nxt = day + dt.timedelta(days=1)
            while not trading_calendar.is_trading_day(nxt):
                nxt += dt.timedelta(days=1)
        if nxt.isocalendar()[:2] != day.isocalendar()[:2]:
            out.append(d)
    return out


def ranking(panel, asset_class, date, sig=None, added=None):
    """Candidates on `date`, best first: [(code, signal, r60)]."""
    sig = signal(panel) if sig is None else sig
    s = sig.loc[date]
    ok = candidates(panel, asset_class, added).loc[date] & s.notna()
    r60 = panel['r60'].loc[date]
    rows = [(c, float(s[c]), float(r60[c]) if pd.notna(r60[c]) else -math.inf) for c in s.index[ok]]
    return sorted(rows, key=lambda x: (x[1], x[2]), reverse=True)


def picks(panel, asset_class, date, n=TOP_N, sig=None, added=None):
    return [c for c, _, _ in ranking(panel, asset_class, date, sig, added)[:n]]


def simulate(panel, asset_class, start, end=None, n=TOP_N, cost=COST, schedule=None, sig=None, added=None, fixed=None):
    """Daily returns of the rule: signal at a week-end close, trade at the next open.

    Each day's return runs from the previous close: overnight (close->open) on the old
    weights, then open->close on the new ones; costs are charged on the traded weight.
    `fixed` ({signal_date: [codes]}, e.g. from ledger.holdings) replaces the ranking: those
    dates become the schedule and their recorded codes the picks. Codes without prices in
    the panel are dropped and reported in `missing`.
    Returns dict(returns, benchmark, equal_weight, holdings=[(signal_date, [codes])],
    turnover, missing), indexed by the session whose close ends each return."""
    close = panel['close']
    cal = list(close.index)
    sig = signal(panel) if sig is None else sig
    C = close.to_numpy(float)
    O = panel['open'].to_numpy(float) if 'open' in panel else C
    O = np.where(np.isfinite(O), O, C)
    S = sig.to_numpy(float)
    R60 = np.nan_to_num(panel['r60'].to_numpy(float), nan=-np.inf)
    cand = candidates(panel, asset_class, added).to_numpy() & np.isfinite(S)
    if fixed is not None:
        schedule = [d for d in fixed if d in close.index]
    sched = set(schedule if schedule is not None else week_ends(cal))
    first = next((i for i, d in enumerate(cal) if d >= start and d in sched), None)
    last = len(cal) - 1 if end is None else max(i for i, d in enumerate(cal) if d <= end)
    empty = pd.Series(dtype=float)
    if first is None or first >= last:
        return dict(returns=empty, benchmark=empty, equal_weight=empty, holdings=[], turnover=0.0, missing=[])
    cols = list(close.columns)
    missing = []
    bi = cols.index(BENCHMARK) if BENCHMARK in cols else None
    w = np.zeros(len(cols))
    out, bench, ew, holdings, turnover = [], [], [], [], 0.0
    pending = None
    with np.errstate(invalid='ignore', divide='ignore'):
        for i in range(first, last):
            gap = np.nan_to_num(O[i + 1] / C[i] - 1)
            day = np.nan_to_num(C[i + 1] / O[i + 1] - 1)
            cc = np.nan_to_num(C[i + 1] / C[i] - 1)
            if cal[i] in sched:
                if fixed is not None:
                    want = fixed[cal[i]]
                    missing += [(cal[i], c) for c in want if c not in cols]
                    order = np.array([cols.index(c) for c in want if c in cols], dtype=int)
                else:
                    idx = np.nonzero(cand[i])[0]
                    order = idx[np.lexsort((-R60[i, idx], -S[i, idx]))][:n]
                pending = np.zeros(len(cols))
                if len(order):
                    pending[order] = 1 / len(order)
                holdings.append((cal[i], [cols[j] for j in order]))
            r_night = float(w @ gap)
            g = w * (1 + gap)
            w = g / g.sum() if g.sum() > 0 else g
            c = 0.0
            if pending is not None:
                trade = float(np.abs(pending - w).sum())
                c, turnover, w, pending = trade * cost, turnover + trade, pending, None
            r_day = float(w @ day)
            out.append((1 + r_night) * (1 + r_day) - 1 - c)
            g = w * (1 + day)
            w = g / g.sum() if g.sum() > 0 else g
            bench.append(float(cc[bi]) if bi is not None else 0.0)
            m = cand[i]
            ew.append(float(cc[m].mean()) if m.any() else 0.0)
    idx = cal[first + 1:last + 1]
    return dict(returns=pd.Series(out, index=idx), benchmark=pd.Series(bench, index=idx),
                equal_weight=pd.Series(ew, index=idx), holdings=holdings, turnover=turnover, missing=missing)


def stats(returns, rf=0.015):
    if len(returns) < 2:
        return dict(total=float((1 + returns).prod() - 1) if len(returns) else 0.0, cagr=None, vol=None, sharpe=None, mdd=None)
    nav = (1 + returns).cumprod()
    years = len(returns) / 252
    vol = float(returns.std() * math.sqrt(252))
    return dict(total=float(nav.iloc[-1] - 1), cagr=float(nav.iloc[-1] ** (1 / years) - 1) if years >= .5 else None,
                vol=vol, sharpe=float((returns.mean() * 252 - rf) / vol) if vol > 0 else None,
                mdd=float((nav / nav.cummax() - 1).min()))
