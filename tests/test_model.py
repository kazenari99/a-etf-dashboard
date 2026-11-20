import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import model
import radar

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/us_model_parity.json').read_text())


class ModelTests(unittest.TestCase):
    def entries(self):
        return json.loads(json.dumps(FIXTURE['entries']))

    def test_pct_against_self_equals_pandas_rank(self):
        df = pd.DataFrame([[3, 1, 2, np.nan], [1, 1, 5, 2]], dtype=float)
        pd.testing.assert_frame_equal(model.pct_against(df, df), df.rank(axis=1, pct=True))

    def test_duplicate_exposure_does_not_stretch_scale(self):
        vals = pd.DataFrame([[.10, .05, .01, .099]], columns=list('ABCD'))
        ref = vals.copy(); ref['D'] = np.nan  # D duplicates A's theme, A represents it
        pct = model.pct_against(vals, ref)
        self.assertEqual(pct.at[0, 'C'], 1 / 3)  # C keeps its place on a 3-name scale
        self.assertAlmostEqual(pct.at[0, 'D'], 2.5 / 3)  # D placed between B and A

    def test_v1_is_published_score_and_v2_is_shadow(self):
        rows, _, regime = radar.analyze(self.entries())
        ranked = [r for r in rows if r['eligible']]
        self.assertTrue(all(isinstance(r['score'], float) for r in ranked))
        self.assertTrue(all('score_v2' in r and 'setup_v2' in r for r in ranked))
        self.assertIn(regime['state'], ('risk_on', 'neutral', 'risk_off'))

    def test_equity_scope_leaves_bonds_unranked(self):
        entries = self.entries()
        p = model.build_panel(entries, '510300')
        out = model.score_panel(p, model.V1.variant('eq', rank_scope='equity'), {'510050': 'bond'})
        self.assertTrue(out['score']['510050'].isna().all())
        self.assertTrue(out['score']['510500'].notna().iloc[-1])

    def test_hysteresis_holds_strong_until_watch_fails(self):
        idx = ['d1', 'd2', 'd3']
        panel = {k: pd.DataFrame({'A': v}, index=idx) for k, v in dict(
            close=[10, 10, 10], dist_ema_atr=[1, 1, 1], r20=[.1, -.01, -.01], r60=[.1, .1, -.1],
            r120=[.1, .1, .1], sma50=[9, 9, 9]).items()}
        panel['trend_aligned'] = pd.DataFrame({'A': [True, True, True]}, index=idx)
        panel['eligible'] = pd.DataFrame({'A': [True, True, True]}, index=idx)
        rs = pd.DataFrame({'A': [.1, .1, .1]}, index=idx)
        plain = model._setups(panel, rs, False)['A'].tolist()
        held = model._setups(panel, rs, True)['A'].tolist()
        self.assertEqual(plain, ['Momentum', 'Pullback watch', 'Avoid / broken'])
        self.assertEqual(held, ['Momentum', 'Momentum', 'Avoid / broken'])

    def test_premium_uses_close_on_nav_date(self):
        bars = [dict(date='2026-11-18', close=1.10), dict(date='2026-11-19', close=1.20)]
        self.assertAlmostEqual(radar.premium(bars, dict(date='2026-11-18', unit_nav=1.0)), .10)
        self.assertIsNone(radar.premium(bars, dict(date='2026-11-01', unit_nav=1.0)))
        self.assertIsNone(radar.premium(bars, None))

    def test_request_nav_picks_latest_valid(self):
        stamp = lambda d: int(pd.Timestamp(d, tz='Asia/Shanghai').timestamp() * 1000)
        payload = dict(code=0, data=dict(item=[dict(nav_date=stamp('2026-11-17'), unit_nav=1.1),
                                               dict(nav_date=stamp('2026-11-18'), unit_nav=1.2),
                                               dict(nav_date=stamp('2026-11-19'), unit_nav=None)]))
        with patch.object(radar, 'api_get', return_value=payload):
            self.assertEqual(radar.request_nav('513100', 'k'), dict(date='2026-11-18', unit_nav=1.2))


if __name__ == '__main__':
    unittest.main()
