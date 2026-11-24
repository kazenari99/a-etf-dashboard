import unittest

from radar import attach_comparison
from universe import ADDED, ASSET_CLASS, CASH_ETF, CROSS_BORDER, ETF_GROUPS, MARKET

# The original 53-ETF list (legacy/etf_dashboard.py, removed; last present in commit ef32a3a).
ORIGINAL_53 = (
    '159326',
    '159338',
    '159516',
    '159530',
    '159538',
    '159558',
    '159605',
    '159611',
    '159713',
    '159755',
    '159819',
    '159840',
    '159866',
    '159915',
    '159928',
    '159930',
    '159940',
    '159980',
    '159985',
    '159992',
    '159995',
    '159996',
    '510050',
    '510300',
    '510500',
    '510880',
    '511010',
    '511260',
    '512010',
    '512100',
    '512170',
    '512200',
    '512400',
    '512760',
    '512800',
    '512880',
    '512890',
    '513060',
    '513100',
    '513130',
    '513330',
    '513500',
    '515060',
    '515080',
    '515120',
    '515170',
    '515220',
    '515790',
    '515880',
    '516160',
    '518880',
    '588000',
    '588200',
)


class UniverseTests(unittest.TestCase):
    def test_expansion_preserves_original_and_has_unique_codes(self):
        codes = [c for items in ETF_GROUPS.values() for c, n in items]
        old = set(ORIGINAL_53)
        self.assertEqual(len(old), 53)
        self.assertEqual(len(codes), 71)
        self.assertEqual(len(set(codes)), 71)
        self.assertTrue(old.issubset(codes))
        self.assertEqual(len(set(codes) - old), 18)
        self.assertNotIn(CASH_ETF[0], codes)  # cash benchmark is fetched, not listed
        self.assertTrue(set(ADDED) <= set(codes))
        self.assertTrue(all(d >= '2026-11-21' for d in ADDED.values()))  # after the paper track began

    def test_asset_types_separated(self):
        groups = {c: g for g, items in ETF_GROUPS.items() for c, n in items}
        self.assertEqual(groups['159980'], '商品')
        self.assertEqual(groups['518880'], '商品')
        self.assertEqual(groups['511010'], '债券')
        self.assertEqual(groups['510880'], '红利策略')
        self.assertEqual(groups['159611'], '公用事业')
        self.assertEqual(groups['512580'], '新能源')
        self.assertEqual(ASSET_CLASS['511380'], 'convertible')
        self.assertEqual(ASSET_CLASS[CASH_ETF[0]], 'cash')

    def test_markets_and_cross_border(self):
        self.assertEqual(MARKET['513100'], '海外')
        self.assertEqual(MARKET['513120'], '港股')
        self.assertEqual(MARKET['510300'], '境内')
        self.assertEqual(set(CROSS_BORDER), {c for c, m in MARKET.items() if m != '境内'})

    def test_display_names_unique(self):
        names = [n for items in ETF_GROUPS.values() for c, n in items]
        self.assertEqual(len(names), len(set(names)))

    def test_universe_version_change_prevents_rank_comparison(self):
        row = dict(ticker='A', score=80, eligible=True, cached=False, setup='Momentum')
        old = dict(asof='2026-11-05', model='v1', provider='test', benchmark='A', universe_version='v1', rows=[row])
        new = old | dict(asof='2026-11-06', universe_version='v2')
        attach_comparison(new, old)
        self.assertIsNone(new['comparison'])
