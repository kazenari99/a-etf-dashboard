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


if __name__ == '__main__':
    unittest.main()
