"""Backtest figures quoted in README must match reports/backtest.json (the single source)."""
import json
from pathlib import Path
import unittest

import radar
import strategy

ROOT = Path(__file__).resolve().parent.parent


def fmt(v):
    return f'{"+" if v >= 0 else "−"}{abs(v) * 100:.1f}%'


class DocsTests(unittest.TestCase):
    def setUp(self):
        self.rule = json.loads((ROOT / 'reports/backtest.json').read_text())['rule']
        self.readme = (ROOT / 'README.md').read_text()

    def test_report_is_for_the_current_rule(self):
        self.assertEqual(self.rule['rule'], strategy.RULE_VERSION)
        self.assertEqual(self.rule['cost'], strategy.COST)

    def test_readme_quotes_the_report(self):
        for key, value in (('strategy', 'cagr'), ('strategy', 'mdd'), ('benchmark', 'cagr'), ('equal_weight', 'cagr')):
            text = fmt(self.rule[key][value])
            self.assertIn(text, self.readme, f'README 中的 {key}.{value} 应为 {text}（来自 reports/backtest.json）')

    def test_page_summary_reads_the_report(self):
        s = radar.backtest_summary()
        self.assertAlmostEqual(s['cagr'], self.rule['strategy']['cagr'])
        self.assertEqual(s['start'], self.rule['start'])


if __name__ == '__main__':
    unittest.main()
