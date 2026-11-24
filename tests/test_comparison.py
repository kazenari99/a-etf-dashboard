import copy
import unittest

from radar import attach_comparison


class ComparisonTests(unittest.TestCase):
    def sample(self, date):
        return dict(
            asof=date,
            model='v1',
            provider='test',
            benchmark='b',
            rows=[
                dict(ticker='A', score=90, setup='Momentum', eligible=True, cached=False),
                dict(ticker='B', score=50, setup='Avoid / broken', eligible=True, cached=False),
            ],
        )

    def test_rank_and_transitions(self):
        old = self.sample('2026-11-05')
        new = self.sample('2026-11-06')
        new['rows'][0].update(score=40, setup='Avoid / broken')
        new['rows'][1].update(score=95, setup='Momentum')
        attach_comparison(new, old)
        self.assertEqual(new['comparison']['changes']['B'], dict(rank_delta=1, entered_strong=True, broken=False))
        self.assertTrue(new['comparison']['changes']['A']['broken'])
        rerun = copy.deepcopy(new)
        attach_comparison(rerun, new)
        self.assertEqual(rerun['comparison'], new['comparison'])

    def test_missing_same_day_and_incomparable(self):
        for kind in ['missing', 'same_day', 'pool', 'cache', 'model', 'future']:
            old = self.sample('2026-11-05')
            new = self.sample('2026-11-06')
            if kind == 'missing':
                old = None
            elif kind == 'same_day':
                old['asof'] = new['asof']
            elif kind == 'pool':
                old['rows'].pop()
            elif kind == 'cache':
                old['rows'][0]['cached'] = True
            elif kind == 'model':
                old['model'] = 'other'
            elif kind == 'future':
                old['asof'] = '2026-11-07'
            attach_comparison(new, old)
            self.assertIsNone(new['comparison'], kind)

    def test_one_missing_or_cached_etf_is_excluded_not_fatal(self):
        def snap(date, scores):
            return dict(
                asof=date,
                model='v1',
                provider='test',
                benchmark='b',
                universe_version='u',
                rows=[
                    dict(ticker=f'T{i:02d}', score=v, setup='Momentum', eligible=True, cached=False)
                    for i, v in enumerate(scores)
                ],
            )

        old = snap('2026-11-05', range(20, 0, -1))
        new = snap('2026-11-06', range(20, 0, -1))
        new['rows'][0].update(eligible=False, score=None)  # T00 lost its score today
        new['rows'][5]['cached'] = True  # T05 only from cache
        new['rows'][19]['score'] = 100  # T19 jumps to the top
        attach_comparison(new, old)
        c = new['comparison']
        self.assertEqual(c['excluded'], ['T00', 'T05'])
        self.assertNotIn('T00', c['changes'])
        self.assertNotIn('T05', c['changes'])
        # Ranked within the 18 common ETFs: T19 goes from 18th to 1st, T01 from 1st to 2nd.
        self.assertEqual(c['changes']['T19']['rank_delta'], 17)
        self.assertEqual(c['changes']['T01']['rank_delta'], -1)
        # Too few in common: comparison paused.
        for r in new['rows'][:4]:
            r['cached'] = True
        attach_comparison(new, old)
        self.assertIsNone(new['comparison'])

    def test_tied_scores_share_rank(self):
        old = self.sample('2026-11-05')
        new = self.sample('2026-11-06')
        new['rows'][1]['score'] = 90
        attach_comparison(new, old)
        self.assertEqual(new['comparison']['changes']['B']['rank_delta'], 1)
