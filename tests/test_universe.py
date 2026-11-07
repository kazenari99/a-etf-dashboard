import unittest
from universe import ETF_GROUPS
from etf_dashboard import ETF_GROUPS as LEGACY
from radar import attach_comparison

class UniverseTests(unittest.TestCase):
    def test_expansion_preserves_original_and_has_unique_codes(self):
        codes=[c for items in ETF_GROUPS.values() for c,n in items]
        old={c for items in LEGACY.values() for c,n in items}
        self.assertEqual(len(codes),66)
        self.assertEqual(len(set(codes)),66)
        self.assertTrue(old.issubset(codes))
        self.assertEqual(len(set(codes)-old),13)
    def test_asset_types_separated(self):
        groups={c:g for g,items in ETF_GROUPS.items() for c,n in items}
        self.assertEqual(groups['159980'],'商品')
        self.assertEqual(groups['518880'],'商品')
        self.assertEqual(groups['511010'],'债券')
        self.assertEqual(groups['510880'],'红利策略')
        self.assertEqual(groups['159611'],'公用事业/环保')
    def test_universe_version_change_prevents_rank_comparison(self):
        row=dict(ticker='A',score=80,eligible=True,cached=False,setup='Momentum')
        old=dict(asof='2026-11-05',model='v1',provider='test',benchmark='A',universe_version='v1',rows=[row])
        new=old|dict(asof='2026-11-06',universe_version='v2')
        attach_comparison(new,old)
        self.assertIsNone(new['comparison'])
