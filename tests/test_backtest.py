import math
import unittest
from unittest.mock import patch
import backtest
import model


class BacktestTests(unittest.TestCase):
    def run_synthetic(self, effect, seed):
        entries, asset, clusters = backtest.synthetic(n=30, days=600, effect=effect, seed=seed)
        with patch.object(backtest, 'CONFIGS', [model.V1, model.V2]):
            return backtest.evaluate(entries, asset, clusters)

    def test_detects_planted_momentum(self):
        res = self.run_synthetic(1.0, 7)
        for cfg in res['configs']:
            self.assertGreater(cfg['h20']['ic_mean'], .05, cfg['name'])
            self.assertGreater(cfg['h20']['q5_q1'], 0, cfg['name'])

    def test_noise_is_not_significant(self):
        res = self.run_synthetic(0.0, 3)
        h = res['configs'][0]['h20']
        self.assertLess(abs(h['ic_mean']), .05)
        self.assertLess(abs(h['ic_t']), 2)

    def test_report_renders(self):
        res = self.run_synthetic(1.0, 7)
        text = backtest.report(res, 'test')
        self.assertIn('Rank IC', text)
        self.assertIn(model.V2.name, text)

    def test_batch_fetch_maps_each_code(self):
        def fake(path, params, key):
            codes = params['thscodes'].split(',')
            return dict(code=0, data=dict(item=[dict(thscode=c, item=[]) for c in codes]))
        with patch.object(backtest.radar, 'api_key', return_value='k'), \
             patch.object(backtest.radar, 'api_get', side_effect=fake) as call, \
             patch.object(backtest.time, 'sleep'), patch.object(backtest, 'CACHE') as cache:
            entries = backtest.fetch()
        n = sum(len(v) for v in backtest.ETF_GROUPS.values())
        self.assertEqual(call.call_count, math.ceil(n / 10))  # 10 codes per request
        self.assertEqual(len(entries), n)
        self.assertTrue(all(len(p['thscodes'].split(',')) <= 10 for (_, p, _), _ in call.call_args_list))
        cache.write_text.assert_called_once()

    def test_batch_permission_error_falls_back_to_single(self):
        def denied(path, params, key):
            raise backtest.radar.APIError(2003, 'test')
        single = dict(rows=[dict(date='2026-11-20', open=1, high=1, low=1, close=1, volume=1, turnover=1)])
        with patch.object(backtest.radar, 'api_key', return_value='k'), \
             patch.object(backtest.radar, 'api_get', side_effect=denied) as batch, \
             patch.object(backtest.radar, 'request_history', return_value=single) as one, \
             patch.object(backtest.time, 'sleep'), patch.object(backtest, 'CACHE'):
            entries = backtest.fetch()
        self.assertEqual(batch.call_count, 1)  # batch tried once, then abandoned
        n = sum(len(v) for v in backtest.ETF_GROUPS.values())
        self.assertEqual(one.call_count, n)
        self.assertEqual(len(entries), n)

    def test_single_permission_error_reports_key_problem(self):
        def denied(*args, **kwargs):
            raise backtest.radar.APIError(2003, 'test')
        with patch.object(backtest.radar, 'api_key', return_value='k'), \
             patch.object(backtest.radar, 'api_get', side_effect=denied), \
             patch.object(backtest.radar, 'request_history', side_effect=denied), \
             patch.object(backtest.time, 'sleep'), patch.object(backtest, 'CACHE'):
            with self.assertRaisesRegex(RuntimeError, 'key 无效'):
                backtest.fetch()

    def test_deflated_sharpe_penalises_more_trials(self):
        import numpy as np
        r = np.random.default_rng(0).normal(.0015, .01, 1000)
        one = backtest.deflated_sharpe(r, [0.0], 1)
        many = backtest.deflated_sharpe(r, list(np.random.default_rng(1).normal(0, .03, 15)), 40)
        self.assertAlmostEqual(one['psr'], one['dsr'])
        self.assertGreater(one['psr'], .9)
        self.assertLess(many['dsr'], many['psr'])
        self.assertGreater(many['sr0_annual'], 0)
        noise = backtest.deflated_sharpe(np.random.default_rng(2).normal(0, .01, 1000), [0.0], 1)
        self.assertLess(noise['psr'], .95)

    def test_rule_robustness_in_report(self):
        res = self.run_synthetic(1.0, 7)
        rob = res['rule']['robustness']
        self.assertEqual(len(rob['costs']), len(backtest.COSTS))
        cagr = [c['cagr'] for c in rob['costs']]
        self.assertEqual(cagr, sorted(cagr, reverse=True))  # higher cost, lower return
        self.assertEqual(sum(g['current'] for g in rob['grid']), 1)
        self.assertGreater(rob['subsample']['runs'], 0)
        self.assertIn('dsr', rob['deflated'])
        text = backtest.report(res, 'test')
        for key in ('交易成本敏感性', '参数网格', '观察池抽样', 'Deflated Sharpe'):
            self.assertIn(key, text)

if __name__ == '__main__':
    unittest.main()
