"""Tests for date intelligence."""
import unittest
from datetime import date, datetime

from src.timeutils.dates import (
    inclusive_datetime_range,
    resolve_period,
    today,
)


class TestDates(unittest.TestCase):
    def setUp(self):
        # Fixed: Thursday 2026-07-23 15:30 Asia/Kolkata
        self.now = datetime(2026, 7, 23, 15, 30, 0)
        self.tz = "Asia/Kolkata"

    def test_today(self):
        self.assertEqual(today(self.tz, self.now), date(2026, 7, 23))

    def test_yesterday(self):
        start, end = resolve_period("yesterday", self.tz, self.now)
        self.assertEqual(start, date(2026, 7, 22))
        self.assertEqual(end, date(2026, 7, 22))

    def test_this_week_monday_start(self):
        # 2026-07-23 is Thursday → week Mon 20 – Sun 26
        start, end = resolve_period("this_week", self.tz, self.now)
        self.assertEqual(start, date(2026, 7, 20))
        self.assertEqual(end, date(2026, 7, 26))

    def test_last_week(self):
        start, end = resolve_period("last_week", self.tz, self.now)
        self.assertEqual(start, date(2026, 7, 13))
        self.assertEqual(end, date(2026, 7, 19))

    def test_this_month(self):
        start, end = resolve_period("this_month", self.tz, self.now)
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 31))

    def test_last_month(self):
        start, end = resolve_period("last_month", self.tz, self.now)
        self.assertEqual(start, date(2026, 6, 1))
        self.assertEqual(end, date(2026, 6, 30))

    def test_last_n_days(self):
        start, end = resolve_period("last_n_days", self.tz, self.now, last_n_days=7)
        self.assertEqual(end, date(2026, 7, 23))
        self.assertEqual(start, date(2026, 7, 17))

    def test_inclusive_range(self):
        start, end = inclusive_datetime_range("2026-07-01", "2026-07-01", self.tz)
        self.assertEqual(start.day, 1)
        self.assertEqual(start.hour, 0)
        self.assertEqual(end.day, 1)
        self.assertGreaterEqual(end.hour, 23)

    def test_unknown_period(self):
        with self.assertRaises(ValueError):
            resolve_period("next_millennium", self.tz, self.now)


if __name__ == "__main__":
    unittest.main()
