import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import model
import radar
import strategy

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/us_model_parity.json').read_text())


def synthetic_panel(days=320):
    """Five equity ETFs with distinct trends + the benchmark, all liquid and aligned."""
    dates = pd.bdate_range('2025-01-02', periods=days).strftime('%Y-%m-%d')
    drift = {'510300': 0.0, '510050': .002, '510500': .001, '512100': -.001, '159915': .0015, '512800': .0005}
    entries = {}
    for code, d in drift.items():
        c = 1.0 * np.exp(np.cumsum(np.full(days, d) + 0.004 * np.sin(np.arange(days) / 7 + len(code))))
        entries[code] = dict(rows=[dict(date=x, open=v, high=v * 1.01, low=v * .99, close=v, volume=1, turnover=1e8)
                                   for x, v in zip(dates, c)])
    return entries, model.build_panel(entries, '510300')


class StrategyTests(unittest.TestCase):
    def test_week_end_respects_holidays(self):
        cal = ['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-08', '2026-10-09']
        # 9-30 (Wed) is the last session before the National Day break -> week-end; 10-09 is Friday.
        self.assertEqual(strategy.week_ends(cal), ['2026-09-30', '2026-10-09'])
        # The latest session (Thursday 2026-10-08 here) is not a week-end: Friday trades.
        self.assertEqual(strategy.week_ends(cal[:4]), ['2026-09-30'])

    def test_ranking_prefers_new_highs_then_r60(self):
        entries, p = synthetic_panel()
        last = p['close'].index[-1]
        ranked = strategy.ranking(p, {}, last)
        nh = [x[1] for x in ranked]
        self.assertEqual(nh, sorted(nh, reverse=True))
        ties = [x for x in ranked if x[1] == ranked[0][1]]
        self.assertEqual([x[2] for x in ties], sorted([x[2] for x in ties], reverse=True))
        self.assertLessEqual(len(strategy.picks(p, {}, last)), strategy.TOP_N)

    def test_bonds_and_illiquid_are_not_candidates(self):
        entries, p = synthetic_panel()
        last = p['close'].index[-1]
        picks = strategy.picks(p, {'510050': 'bond'}, last, n=10)
        self.assertNotIn('510050', picks)
        p['adtv20'] = p['adtv20'].copy(); p['adtv20']['510500'] = 1e6
        self.assertNotIn('510500', strategy.picks(p, {}, last, n=10))

    def test_simulation_charges_costs_and_is_causal(self):
        entries, p = synthetic_panel()
        start = p['close'].index[260]
        free = strategy.simulate(p, {}, start, cost=0)
        paid = strategy.simulate(p, {}, start, cost=.001)
        self.assertGreater(free['returns'].sum(), paid['returns'].sum())
        self.assertGreater(paid['turnover'], 0)
        # Changing prices after a date must not change returns up to that date.
        cut = p['close'].index[-20]
        early = strategy.simulate(p, {}, start, end=cut, cost=0)['returns']
        pd.testing.assert_series_equal(early, free['returns'].loc[:cut])

    def test_weekly_summary_in_payload(self):
        entries, _ = synthetic_panel()
        with patch.object(radar, 'ASSET_CLASS', {}), patch.object(strategy, 'TRACK_START', '2026-01-02'):
            rows, latest, regime, weekly = radar.analyze_full(entries)
        self.assertIn(weekly['holding_from'], ('this', 'next'))
        self.assertTrue(1 <= len(weekly['picks']) <= strategy.TOP_N)
        self.assertIsNotNone(weekly['track'])
        self.assertEqual(weekly['track']['nav'][-1]['date'], latest)

    def test_short_history_gives_no_weekly(self):
        rows, latest, regime, weekly = radar.analyze_full(json.loads(json.dumps(FIXTURE['entries'])))
        self.assertIsNone(weekly)  # fixture has < 250 sessions: no near-high, no picks

    def test_fetch_window_covers_lookback_and_track(self):
        self.assertGreaterEqual(radar.fetch_days(), 560)
        with patch.object(radar, 'completed_cutoff', return_value=pd.Timestamp('2027-06-30').date()):
            self.assertGreater(radar.fetch_days(), 560)

    def test_index_overview_in_regime(self):
        entries, _ = synthetic_panel()
        with patch.object(radar, 'ASSET_CLASS', {}):
            rows, latest, regime, weekly = radar.analyze_full(entries)
        idx = {x['ticker']: x for x in regime['indices']}
        self.assertEqual(set(idx), {c for c, _ in radar.INDEX_ETFS} & set(entries))
        for x in idx.values():
            self.assertIn(x['trend'], ('up', 'down', 'range'))
            self.assertEqual(set(x['above']), {'50', '120', '250'})
            self.assertLessEqual(x['near_high'], 0)

    def test_added_members_only_from_their_date(self):
        entries, p = synthetic_panel()
        dates = list(p['close'].index)
        cut = dates[-30]
        ok = strategy.candidates(p, {}, added={'510050': cut})
        self.assertFalse(ok['510050'].loc[:dates[-31]].any())
        self.assertTrue(ok['510050'].loc[cut:].equals(strategy.candidates(p, {}, added={})['510050'].loc[cut:]))

    def test_cash_hurdle_and_domestic_breadth(self):
        entries, p = synthetic_panel()
        fixed = model.cash_hurdle(p)
        self.assertAlmostEqual(fixed.iloc[-1], (1 + model.CASH_RATE) ** (120 / 252) - 1)
        series = model.cash_hurdle(p, cash='512800')
        self.assertAlmostEqual(series.iloc[-1], p['r120']['512800'].iloc[-1])
        all_eq = model.regime(p, {})['breadth60'].iloc[-1]
        dom = model.regime(p, {}, market={'510050': '海外', '159915': '海外'})['breadth60'].iloc[-1]
        last = p['r60'].iloc[-1].drop(['510050', '159915'])
        self.assertAlmostEqual(dom, (last > 0).mean())
        self.assertIsNotNone(all_eq)

    def test_non_equity_rows_have_no_score_but_absolute_label(self):
        entries, _ = synthetic_panel()
        classes = {'512800': 'bond'}
        with patch.object(radar, 'ASSET_CLASS', classes):
            rows, latest, regime, weekly = radar.analyze_full(entries)
        by = {r['ticker']: r for r in rows}
        if by.get('512800', {}).get('eligible'):
            self.assertIsNone(by['512800']['score'])
            self.assertIn(by['512800']['setup'], ('Absolute up', 'Absolute down'))
        self.assertTrue(all(isinstance(r['score'], float) for r in rows if r['eligible'] and classes.get(r['ticker'], 'equity') == 'equity'))

    def test_v2_signal_skips_recent_sessions(self):
        entries, p = synthetic_panel()
        pd.testing.assert_frame_equal(strategy.signal(p), strategy.near_high(p).shift(strategy.SKIP))
        self.assertEqual(strategy.SKIP, 5)

    def test_next_open_execution_misses_the_gap(self):
        """A pick that gaps up between the signal close and the next open must not earn the gap."""
        entries, p = synthetic_panel()
        cal = list(p['close'].index)
        ends = strategy.week_ends(cal)
        d = ends[-3]
        i = cal.index(d)
        winner = strategy.picks(p, {}, d)[0]
        bumped = {k: dict(v, rows=[dict(r) for r in v['rows']]) for k, v in entries.items()}
        for r in bumped[winner]['rows'][i + 1:]:
            for f in ('open', 'high', 'low', 'close'):
                r[f] *= 1.10                         # +10% overnight jump right after the signal
        q = model.build_panel(bumped, '510300')
        base = strategy.simulate(p, {}, d, cost=0)['returns']
        jump = strategy.simulate(q, {}, d, cost=0)['returns']
        # Same picks on the signal day; the first-day return must not include the 10% gap.
        self.assertEqual(strategy.picks(q, {}, d)[0], winner)
        self.assertAlmostEqual(jump.iloc[0], base.iloc[0], places=6)

    def test_weekly_trades_partition_the_picks(self):
        entries, _ = synthetic_panel()
        with patch.object(radar, 'ASSET_CLASS', {}), patch.object(strategy, 'TRACK_START', '2026-01-02'):
            rows, latest, regime, w = radar.analyze_full(entries)
        cur = [x['ticker'] for x in w['picks']]
        self.assertEqual(sorted(w['buy'] + w['hold']), sorted(cur))
        self.assertFalse(set(w['sell']) & set(cur))
        self.assertGreater(w['trade_date'], w['rebalance_date'])
        self.assertEqual(w['track']['execution'], 'next_open')
        self.assertEqual(w['track']['legacy']['rule'], strategy.LEGACY_RULE)
        for x in w['picks']:
            self.assertIn('signal', x)


if __name__ == '__main__':
    unittest.main()
