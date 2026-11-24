"""Append-only record of the weekly picks, so the paper track cannot be rewritten later.

The page used to rebuild the paper track from prices on every run. Any later change to the
universe, ADDED dates, filters or rule code would then silently change past holdings. The
ledger fixes the holdings at the time they were first computed: entries are only appended,
never edited, and the published track is simulated from these holdings. Recomputing the
same weeks with today's code is kept as a check (`mismatches`), not as the source.

track/ledger.json is committed by the publishing workflow after each run.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import strategy
import trading_calendar

PATH = Path(__file__).resolve().parent / 'track/ledger.json'
TZ = dt.timezone(dt.timedelta(hours=8))
OPEN = dt.time(9, 30)


def empty():
    return dict(note='Append-only weekly picks; see ledger.py. Do not edit past entries.', entries=[])


def load(path=None):
    try:
        data = json.loads(Path(path or PATH).read_text())
    except FileNotFoundError:
        return empty()
    if not isinstance(data, dict) or not isinstance(data.get('entries'), list):
        raise ValueError(f'{path} 格式无效；请从 git 历史恢复，不要用重算结果覆盖。')
    return data


def save(data, path=None):
    path = Path(path or PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    tmp.replace(path)


def next_session(day):
    nxt = dt.date.fromisoformat(day) + dt.timedelta(days=1)
    while not trading_calendar.is_trading_day(nxt):
        nxt += dt.timedelta(days=1)
    return nxt.isoformat()


def update(data, panel, asset_class, latest, universe_version, now=None, sig=None):
    """Append an entry for every completed week-end signal since TRACK_START that the ledger
    lacks. Existing entries are left untouched. Returns the signal dates appended."""
    now = now or dt.datetime.now(TZ)
    sig = strategy.signal(panel) if sig is None else sig
    have = {e['signal_date'] for e in data['entries']}
    added = []
    for d in strategy.week_ends(list(panel['close'].index)):
        if d < strategy.TRACK_START or d > latest or d in have:
            continue
        ranked = strategy.ranking(panel, asset_class, d, sig)[:strategy.TOP_N]
        if not ranked:
            continue
        trade = next_session(d)
        data['entries'].append(dict(
            signal_date=d, trade_date=trade, rule=strategy.RULE_VERSION, universe_version=universe_version,
            picks=[dict(ticker=c, signal=round(s, 6)) for c, s, _ in ranked],
            recorded_at=now.isoformat(timespec='seconds'),
            # True when the entry was first written after the trade-date open, i.e. the
            # record could not have been acted on as written (e.g. the pipeline was down).
            recorded_after_trade=now >= dt.datetime.combine(dt.date.fromisoformat(trade), OPEN, TZ)))
        added.append(d)
    data['entries'].sort(key=lambda e: e['signal_date'])
    return added


def holdings(data):
    return {e['signal_date']: [p['ticker'] for p in e['picks']] for e in data['entries']}


def mismatches(data, panel, asset_class, sig=None):
    """Signal dates whose recorded picks differ from a recomputation with today's code/data
    (only entries of the current rule; older rules are expected to differ)."""
    sig = strategy.signal(panel) if sig is None else sig
    out = []
    for e in data['entries']:
        if e.get('rule') != strategy.RULE_VERSION or e['signal_date'] not in panel['close'].index:
            continue
        now = strategy.picks(panel, asset_class, e['signal_date'], sig=sig)
        if now != [p['ticker'] for p in e['picks']]:
            out.append(e['signal_date'])
    return out
