import datetime as dt
import unittest

import radar
import trading_calendar as cal


class CalendarTests(unittest.TestCase):
    def test_national_day_resolves_to_last_session(self):
        for day in (1, 5, 7):
            now = dt.datetime(2026, 10, day, 16, tzinfo=radar.TZ)
            self.assertEqual(radar.completed_cutoff(now), dt.date(2026, 9, 30))
        # Before the close on the first session after the break, the last complete bar is still 9-30.
        self.assertEqual(radar.completed_cutoff(dt.datetime(2026, 10, 8, 10, tzinfo=radar.TZ)), dt.date(2026, 9, 30))
        self.assertEqual(radar.completed_cutoff(dt.datetime(2026, 10, 8, 16, tzinfo=radar.TZ)), dt.date(2026, 10, 8))

    def test_single_day_holidays(self):
        self.assertEqual(radar.completed_cutoff(dt.datetime(2026, 6, 19, 16, tzinfo=radar.TZ)), dt.date(2026, 6, 18))
        self.assertEqual(radar.completed_cutoff(dt.datetime(2026, 2, 23, 16, tzinfo=radar.TZ)), dt.date(2026, 2, 13))

    def test_2026_closure_count(self):
        self.assertEqual(sum(d.year == 2026 for d in cal.HOLIDAYS), 19)
        self.assertTrue(all(d.weekday() < 5 for d in cal.HOLIDAYS))
        self.assertTrue(cal.known(2026))

    def test_2027_from_state_council_notice(self):
        self.assertTrue(cal.known(2027))
        self.assertEqual(sum(d.year == 2027 for d in cal.HOLIDAYS), 18)
        for closed in (
            '2027-01-01',
            '2027-02-05',
            '2027-02-12',
            '2027-04-05',
            '2027-05-03',
            '2027-05-05',
            '2027-06-09',
            '2027-09-15',
            '2027-10-01',
            '2027-10-07',
        ):
            self.assertFalse(cal.is_trading_day(dt.date.fromisoformat(closed)), closed)
        # Make-up workdays on weekends never trade; the first sessions after each break do.
        for day in ('2027-01-31', '2027-02-14', '2027-05-08', '2027-09-26', '2027-10-09'):
            self.assertFalse(cal.is_trading_day(dt.date.fromisoformat(day)), day)
        for day in ('2027-01-04', '2027-02-15', '2027-04-06', '2027-05-06', '2027-10-08'):
            self.assertTrue(cal.is_trading_day(dt.date.fromisoformat(day)), day)

    def test_year_end_cutoff_and_week_end(self):
        import strategy

        # 2027-01-01 (Fri) is closed, so Thursday 2026-12-31 closes the ISO week.
        self.assertEqual(radar.completed_cutoff(dt.datetime(2027, 1, 1, 16, tzinfo=radar.TZ)), dt.date(2026, 12, 31))
        self.assertEqual(strategy.week_ends(['2026-12-29', '2026-12-30', '2026-12-31']), ['2026-12-31'])

    def test_missing_years_warns_from_december(self):
        self.assertEqual(cal.missing_years(dt.date(2027, 11, 30)), [])
        self.assertEqual(cal.missing_years(dt.date(2027, 12, 1)), [2028])
        self.assertEqual(cal.missing_years(dt.date(2028, 3, 1)), [2028])
        self.assertTrue(cal.is_trading_day(dt.date(2028, 1, 3)))  # unknown year: weekdays only


if __name__ == '__main__':
    unittest.main()
