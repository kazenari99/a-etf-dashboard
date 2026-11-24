import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_strategy import synthetic_panel

import ledger
import radar
import strategy

TZ = ledger.TZ


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.entries, self.panel = synthetic_panel()
        self.cal = list(self.panel['close'].index)
        self.ends = strategy.week_ends(self.cal)
        self.start = self.ends[-6]
        p = patch.object(strategy, 'TRACK_START', self.start)
        p.start()
        self.addCleanup(p.stop)

    def test_appends_each_week_once_and_never_edits(self):
        book = ledger.empty()
        latest = self.cal[-1]
        added = ledger.update(book, self.panel, {}, latest, 'u1')
        self.assertEqual(added, [d for d in self.ends if d >= self.start])
        first = copy.deepcopy(book)
        # A later run with different data/universe must not touch recorded weeks.
        self.assertEqual(ledger.update(book, self.panel, {'510050': 'bond'}, latest, 'u2'), [])
        self.assertEqual(book, first)
        for e in book['entries']:
            self.assertEqual(e['trade_date'], ledger.next_session(e['signal_date']))
            self.assertEqual(e['rule'], strategy.RULE_VERSION)
            self.assertEqual(len(e['picks']), min(strategy.TOP_N, len(e['picks'])))

    def test_recorded_after_trade_flag(self):
        d = self.ends[-1]
        before = dt.datetime.combine(dt.date.fromisoformat(d), dt.time(20), TZ)
        after = dt.datetime.combine(dt.date.fromisoformat(ledger.next_session(d)), dt.time(10), TZ)
        a, b = ledger.empty(), ledger.empty()
        ledger.update(a, self.panel, {}, d, 'u', now=before)
        ledger.update(b, self.panel, {}, d, 'u', now=after)
        self.assertFalse(a['entries'][-1]['recorded_after_trade'])
        self.assertTrue(b['entries'][-1]['recorded_after_trade'])

    def test_fixed_holdings_match_recomputation_and_win_over_it(self):
        book = ledger.empty()
        ledger.update(book, self.panel, {}, self.cal[-1], 'u')
        held = ledger.holdings(book)
        a = strategy.simulate(self.panel, {}, self.start)
        b = strategy.simulate(self.panel, {}, self.start, fixed=held)
        self.assertEqual(a['returns'].round(12).tolist(), b['returns'].round(12).tolist())
        self.assertEqual(ledger.mismatches(book, self.panel, {}), [])
        # Tamper with a recorded week: the track follows the record and the check flags it.
        wk = book['entries'][0]
        wk['picks'] = [dict(ticker='510300', signal=0.0)]
        c = strategy.simulate(self.panel, {}, self.start, fixed=ledger.holdings(book))
        self.assertEqual(c['holdings'][0][1], ['510300'])
        self.assertEqual(ledger.mismatches(book, self.panel, {}), [wk['signal_date']])

    def test_removed_member_is_reported_not_crashing(self):
        book = ledger.empty()
        ledger.update(book, self.panel, {}, self.cal[-1], 'u')
        book['entries'][0]['picks'].append(dict(ticker='999999', signal=0.0))
        sim = strategy.simulate(self.panel, {}, self.start, fixed=ledger.holdings(book))
        self.assertIn('999999', {c for _, c in sim['missing']})

    def test_weekly_summary_uses_ledger(self):
        book = ledger.empty()
        with patch.object(radar, 'ASSET_CLASS', {}):
            rows, latest, regime, w = radar.analyze_full(self.entries, book)
        self.assertTrue(book['entries'])
        self.assertEqual(w['ledger']['source'], 'ledger')
        self.assertEqual(w['ledger']['mismatches'], [])
        self.assertEqual([x['ticker'] for x in w['picks']], ledger.holdings(book)[w['rebalance_date']])
        # The recorded picks are shown even if today's code would choose differently.
        book['entries'][-1]['picks'] = [dict(ticker='510300', signal=-0.5)]
        with patch.object(radar, 'ASSET_CLASS', {}):
            *_, w2 = radar.analyze_full(self.entries, book)
        if book['entries'][-1]['signal_date'] == w2['rebalance_date']:
            self.assertEqual([x['ticker'] for x in w2['picks']], ['510300'])
        self.assertIn(book['entries'][-1]['signal_date'], w2['ledger']['mismatches'])

    def test_load_save_roundtrip_and_rejects_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'track/ledger.json'
            self.assertEqual(ledger.load(path), ledger.empty())
            book = ledger.empty()
            ledger.update(book, self.panel, {}, self.cal[-1], 'u')
            ledger.save(book, path)
            self.assertEqual(ledger.load(path), json.loads(json.dumps(book)))
            path.write_text('[]')
            with self.assertRaises(ValueError):
                ledger.load(path)


if __name__ == '__main__':
    unittest.main()
