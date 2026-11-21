"""Weekly rotation into the equity ETFs closest to their 250-session closing high.

Rule (frozen 2026-11-21, after the 2022-12..2026-11 backtest in backtest.py):
  * On the last trading session of each calendar week, rank equity ETFs (A-share and
    cross-border; not bonds/commodities) with >= 2000万 yuan 20-day average turnover by
    close / max(close over 250 sessions) - 1. Ties (several at a new high) break on the
    60-day return.
  * Hold the top 5 equally weighted from the next session until the next week-end.
  * The paper track starts at TRACK_START and is rebuilt from prices on every run, so it
    needs no stored state; everything after TRACK_START is out-of-sample.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

import trading_calendar

LOOKBACK = 250
TOP_N = 5
MIN_ADTV = 2e7
COST = 0.001          # per side; ETF commission + spread, conservative
TRACK_START = '2026-11-20'
BENCHMARK = '510300'
RULE_VERSION = 'near-high-250-top5-weekly-v1'


def near_high(panel):
    close = panel['close']
    return close / close.rolling(LOOKBACK, min_periods=LOOKBACK).max() - 1


def candidates(panel, asset_class):
    equity = np.array([asset_class.get(t, 'equity') == 'equity' for t in panel['close'].columns])
    return panel['eligible'] & equity & (panel['adtv20'] >= MIN_ADTV)


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


def ranking(panel, asset_class, date):
    """Candidates on `date`, best first: [(code, near_high, r60)]."""
    nh = near_high(panel).loc[date]
    ok = candidates(panel, asset_class).loc[date] & nh.notna()
    r60 = panel['r60'].loc[date]
    rows = [(c, float(nh[c]), float(r60[c]) if pd.notna(r60[c]) else -math.inf) for c in nh.index[ok]]
    return sorted(rows, key=lambda x: (x[1], x[2]), reverse=True)


def picks(panel, asset_class, date, n=TOP_N):
    return [c for c, _, _ in ranking(panel, asset_class, date)[:n]]


def simulate(panel, asset_class, start, end=None, n=TOP_N, cost=COST, schedule=None):
    """Daily returns of the rule from the first rebalance on/after `start`.

    Returns dict(returns, benchmark, equal_weight, holdings=[(date, [codes])], turnover)."""
    close = panel['close']
    cal = list(close.index)
    ret = close.pct_change().fillna(0.0)
    sched = set(schedule if schedule is not None else week_ends(cal))
    cand = candidates(panel, asset_class)
    first = next((i for i, d in enumerate(cal) if d >= start and d in sched), None)
    last = len(cal) - 1 if end is None else max(i for i, d in enumerate(cal) if d <= end)
    w = pd.Series(0.0, index=close.columns)
    out, bench, ew, holdings, turnover = [], [], [], [], 0.0
    if first is None:
        empty = pd.Series(dtype=float)
        return dict(returns=empty, benchmark=empty, equal_weight=empty, holdings=[], turnover=0.0)
    for i in range(first, last):
        d = cal[i]
        c = 0.0
        if d in sched:
            sel = picks(panel, asset_class, d, n)
            new = pd.Series(0.0, index=close.columns)
            if sel:
                new[sel] = 1 / len(sel)
            trade = float((new - w).abs().sum())
            c, turnover, w = trade * cost, turnover + trade, new
            holdings.append((d, sel))
        r = ret.iloc[i + 1]
        out.append(float((w * r).sum()) - c)
        bench.append(float(r.get(BENCHMARK, 0.0)))
        m = cand.iloc[i]
        ew.append(float(r[m].mean()) if m.any() else 0.0)
        grown = w * (1 + r)
        w = grown / grown.sum() if grown.sum() > 0 else grown
    idx = cal[first + 1:last + 1]
    return dict(returns=pd.Series(out, index=idx), benchmark=pd.Series(bench, index=idx),
                equal_weight=pd.Series(ew, index=idx), holdings=holdings, turnover=turnover)


def stats(returns, rf=0.015):
    if len(returns) < 2:
        return dict(total=float((1 + returns).prod() - 1) if len(returns) else 0.0, cagr=None, vol=None, sharpe=None, mdd=None)
    nav = (1 + returns).cumprod()
    years = len(returns) / 252
    vol = float(returns.std() * math.sqrt(252))
    return dict(total=float(nav.iloc[-1] - 1), cagr=float(nav.iloc[-1] ** (1 / years) - 1) if years >= .5 else None,
                vol=vol, sharpe=float((returns.mean() * 252 - rf) / vol) if vol > 0 else None,
                mdd=float((nav / nav.cummax() - 1).min()))
