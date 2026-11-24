import datetime as dt
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import radar

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/us_model_parity.json').read_text())


class RadarTests(unittest.TestCase):
    def entries(self):
        return json.loads(json.dumps(FIXTURE['entries']))

    def test_existing_us_model_numerical_parity(self):
        entries = self.entries()
        rows, latest = radar.metrics(entries)
        actual = {r['ticker']: r for r in rows}
        # Score/setup parity is checked on model.V1 (the US formula); production publishes PROD.
        v1 = radar.model.score_panel(radar.model.build_panel(entries, radar.BENCHMARK), radar.model.V1)
        for r in rows:
            if r['eligible']:
                r.update(score=float(v1['score'].at[latest, r['ticker']]), setup=v1['setup'].at[latest, r['ticker']])
        for expected in FIXTURE['expected']:
            result = actual[expected['ticker']]
            for key in (
                'score',
                'r20',
                'r60',
                'r120',
                'rs20',
                'rs60',
                'rs120',
                'ema20',
                'sma50',
                'sma120',
                'atr14',
                'atr_pct',
                'dist_ema_atr',
                'from_high120',
                'breakout_trigger',
                'pullback_low',
                'pullback_high',
                'stop_ref',
                'stop_pct',
                'vol20_ann',
                'adtv20',
            ):
                self.assertAlmostEqual(result[key], expected[key], places=10, msg=f'{expected["ticker"]} {key}')
            self.assertEqual(result['setup'], expected['setup'])
            self.assertEqual(result['trend_aligned'], expected['trend_aligned'])

    def test_mismatched_calendar_excluded(self):
        entries = self.entries()
        entries['510050']['rows'].pop(-20)
        rows, _ = radar.metrics(entries)
        self.assertIsNone(next(r for r in rows if r['ticker'] == '510050')['score'])

    def test_short_history_excluded(self):
        entries = self.entries()
        entries['510050']['rows'] = entries['510050']['rows'][-120:]
        rows, _ = radar.metrics(entries)
        self.assertFalse(next(r for r in rows if r['ticker'] == '510050')['eligible'])

    def test_stale_series_excluded(self):
        entries = self.entries()
        entries['510050']['rows'].pop()
        rows, _ = radar.metrics(entries)
        self.assertFalse(next(r for r in rows if r['ticker'] == '510050')['eligible'])

    def test_incomplete_daily_bar_cutoff(self):
        now = dt.datetime(2026, 9, 23, 14, tzinfo=radar.TZ)
        self.assertEqual(radar.completed_cutoff(now), dt.date(2026, 9, 22))
        self.assertEqual(radar.completed_cutoff(now.replace(hour=16)), dt.date(2026, 9, 23))

    def test_weekend_cutoff(self):
        self.assertEqual(radar.completed_cutoff(dt.datetime(2026, 9, 20, 16, tzinfo=radar.TZ)), dt.date(2026, 9, 18))

    def test_normalization_rejects_invalid_ohlc_and_future(self):
        stamp = int(dt.datetime(2026, 9, 23, tzinfo=radar.TZ).timestamp() * 1000)
        row = dict(date_ms=stamp, open_price=1, high_price=2, low_price=0.5, close_price=1.5, volume=100, turnover=150)
        self.assertEqual(len(radar.normalize([row, row], dt.date(2026, 9, 23))), 1)
        self.assertFalse(radar.normalize([row], dt.date(2026, 9, 22)))
        row['high_price'] = 0.1
        self.assertFalse(radar.normalize([row], dt.date(2026, 9, 23)))

    def test_auth_failure_not_retried(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b'{"code":2003,"request_id":"test"}'

        with patch.object(radar.urllib.request, 'urlopen', return_value=Response()) as call:
            with self.assertRaises(radar.APIError):
                radar.request_history('510300', 'test-not-a-key')
        self.assertEqual(call.call_count, 1)

    def test_429_business_error_retries(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b'{"code":4001,"request_id":"test"}'

        with (
            patch.object(radar.urllib.request, 'urlopen', return_value=Response()) as call,
            patch.object(radar.time, 'sleep'),
        ):
            with self.assertRaises(radar.APIError):
                radar.request_history('510300', 'test-not-a-key')
        self.assertEqual(call.call_count, 4)

    def test_http_auth_failure_aborts_without_retry(self):
        import urllib.error

        error = urllib.error.HTTPError('https://example.invalid', 401, 'Unauthorized', {}, None)
        with (
            patch.object(radar.urllib.request, 'urlopen', side_effect=error) as call,
            patch.object(radar.time, 'sleep'),
        ):
            with self.assertRaises(radar.AuthError):
                radar.request_history('510300', 'test-not-a-key')
        self.assertEqual(call.call_count, 1)

    def test_auth_error_stops_whole_build(self):
        with (
            patch.object(radar, 'api_key', return_value='test-not-a-key'),
            patch.object(radar, 'CACHE', Path('/nonexistent/cache.json')),
            patch.object(radar, 'request_history', side_effect=radar.AuthError('HTTP 401')) as call,
            patch.object(radar, 'publish') as publish,
        ):
            with self.assertRaises(radar.AuthError):
                radar.build()
        self.assertEqual(call.call_count, 1)
        publish.assert_not_called()

    def test_extra_session_excludes_only_that_etf(self):
        entries = self.entries()
        rows = entries['510050']['rows']
        extra = dict(rows[-1], date='2099-01-01')
        rows.append(extra)
        result, latest = radar.metrics(entries)
        by = {r['ticker']: r for r in result}
        self.assertEqual(latest, entries[radar.BENCHMARK]['rows'][-1]['date'])
        self.assertFalse(by['510050']['eligible'])
        self.assertTrue(all(by[t]['eligible'] for t in entries if t != '510050'))

    def test_coverage_threshold(self):
        def rows(ok, total):
            return [dict(eligible=i < ok) for i in range(total)]

        radar.check_coverage(rows(60, 66))
        for ok in (59, 0):
            with self.assertRaises(RuntimeError):
                radar.check_coverage(rows(ok, 66))

    def test_render_requires_cache_for_whole_universe(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / 'cache.json'
            cache.write_text(json.dumps(self.entries()))
            with patch.object(radar, 'CACHE', cache), patch.object(radar, 'publish') as publish:
                with self.assertRaises(RuntimeError):
                    radar.build(render=True)
            publish.assert_not_called()

    def test_previous_snapshot_prefers_newest_source(self):
        local = dict(asof='2026-11-19', generated='a', rows=[])
        remote = dict(asof='2026-11-20', generated='b', rows=[])
        with (
            patch.object(radar, 'local_snapshot', return_value=local),
            patch.object(radar, 'published_snapshot', return_value=remote),
        ):
            self.assertEqual(radar.previous_snapshot()['asof'], '2026-11-20')
        with (
            patch.object(radar, 'local_snapshot', return_value=local),
            patch.object(radar, 'published_snapshot', return_value=None),
        ):
            self.assertEqual(radar.previous_snapshot()['asof'], '2026-11-19')
        with (
            patch.object(radar, 'local_snapshot', return_value=None),
            patch.object(radar, 'published_snapshot', return_value=None),
        ):
            self.assertIsNone(radar.previous_snapshot())

    def test_comparison_ignores_unscored_rows(self):
        eq = lambda t, sc, st='Momentum': dict(ticker=t, score=sc, setup=st, eligible=True, cached=False)
        bond = dict(ticker='B', score=None, setup='Absolute up', eligible=True, cached=False)
        meta = dict(model='m', provider='p', benchmark='A', universe_version='u')
        old = dict(meta, asof='2026-11-19', rows=[eq('A', 80), eq('C', 60), bond])
        new = dict(meta, asof='2026-11-20', rows=[eq('A', 50), eq('C', 70, 'Pullback watch'), bond])
        radar.attach_comparison(new, old)
        self.assertEqual(set(new['comparison']['changes']), {'A', 'C'})
        self.assertEqual(new['comparison']['changes']['C']['rank_delta'], 1)

    def test_rows_do_not_embed_price_history(self):
        rows, latest = radar.metrics(self.entries())
        self.assertTrue(any(r['eligible'] for r in rows))
        self.assertFalse(any('history' in r for r in rows))  # the page never used it; ~450 KB per page

    def test_published_urls_configurable(self):
        with patch.dict('os.environ', {'PUBLISHED_URLS': ''}):
            self.assertEqual(radar.published_urls(), list(radar.PUBLISHED_URLS))
        with patch.dict('os.environ', {'PUBLISHED_URLS': 'https://a.example/, https://b.example/'}):
            self.assertEqual(radar.published_urls(), ['https://a.example/', 'https://b.example/'])
        with (
            patch.object(radar, 'local_snapshot', return_value=None),
            patch.object(radar, 'published_urls', return_value=['u1', 'u2']),
            patch.object(
                radar,
                'published_snapshot',
                side_effect=lambda u: dict(asof={'u1': '2026-11-19', 'u2': '2026-11-20'}[u]),
            ),
        ):
            self.assertEqual(radar.previous_snapshot()['asof'], '2026-11-20')


if __name__ == '__main__':
    unittest.main()
