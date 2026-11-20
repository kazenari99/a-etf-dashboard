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
        self.assertEqual(call.call_count, 7)  # 66 codes, 10 per request
        self.assertEqual(len(entries), 66)
        self.assertTrue(all(len(p['thscodes'].split(',')) <= 10 for (_, p, _), _ in call.call_args_list))
        cache.write_text.assert_called_once()


if __name__ == '__main__':
    unittest.main()
