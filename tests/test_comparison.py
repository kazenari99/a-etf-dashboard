import copy
import unittest
from radar import attach_comparison

class ComparisonTests(unittest.TestCase):
    def sample(self, date):
        return dict(asof=date,model='v1',provider='test',benchmark='b',rows=[
            dict(ticker='A',score=90,setup='Momentum',eligible=True,cached=False),
            dict(ticker='B',score=50,setup='Avoid / broken',eligible=True,cached=False)])
    def test_rank_and_transitions(self):
        old=self.sample('2026-11-05');new=self.sample('2026-11-06')
        new['rows'][0].update(score=40,setup='Avoid / broken')
        new['rows'][1].update(score=95,setup='Momentum')
        attach_comparison(new,old)
        self.assertEqual(new['comparison']['changes']['B'],dict(rank_delta=1,entered_strong=True,broken=False))
        self.assertTrue(new['comparison']['changes']['A']['broken'])
        rerun=copy.deepcopy(new);attach_comparison(rerun,new)
        self.assertEqual(rerun['comparison'],new['comparison'])
    def test_missing_same_day_and_incomparable(self):
        for kind in ['missing','same_day','pool','cache','model','future']:
            old=self.sample('2026-11-05');new=self.sample('2026-11-06')
            if kind=='missing':old=None
            elif kind=='same_day':old['asof']=new['asof']
            elif kind=='pool':old['rows'].pop()
            elif kind=='cache':old['rows'][0]['cached']=True
            elif kind=='model':old['model']='other'
            elif kind=='future':old['asof']='2026-11-07'
            attach_comparison(new,old)
            self.assertIsNone(new['comparison'],kind)
    def test_tied_scores_share_rank(self):
        old=self.sample('2026-11-05');new=self.sample('2026-11-06')
        new['rows'][1]['score']=90
        attach_comparison(new,old)
        self.assertEqual(new['comparison']['changes']['B']['rank_delta'],1)
