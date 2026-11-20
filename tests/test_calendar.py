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

    def test_2026_closure_count_and_unknown_year(self):
        self.assertEqual(sum(d.year == 2026 for d in cal.HOLIDAYS), 19)
        self.assertTrue(all(d.weekday() < 5 for d in cal.HOLIDAYS))
        self.assertTrue(cal.known(2026))
        self.assertFalse(cal.known(2027))
        self.assertTrue(cal.is_trading_day(dt.date(2027, 1, 4)))  # falls back to weekdays


if __name__ == '__main__':
    unittest.main()
