"""Tests for the council hours parser. Run: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from hours import ALL_DAYS, ALWAYS, OTHER_TIMES, complement, is_active, parse  # noqa: E402

MON, TUE, FRI, SAT, SUN = 0, 1, 4, 5, 6
WEEKDAYS = 0b0011111


def hm(h, m=0):
    return h * 60 + m


class ParseSigns(unittest.TestCase):
    def test_simple_weekday_range(self):
        self.assertEqual(parse("MON-FRI:7am-9am "), [(WEEKDAYS, hm(7), hm(9))])

    def test_blank_day_inherits_from_next_segment(self):
        self.assertEqual(
            parse(":7am-9am ,MON-FRI:4pm-6pm "),
            [(WEEKDAYS, hm(7), hm(9)), (WEEKDAYS, hm(16), hm(18))],
        )

    def test_start_without_meridiem(self):
        self.assertEqual(parse(":7-9:30am ,MON-FRI:3:30-7pm"),
                         [(WEEKDAYS, hm(7), hm(9, 30)), (WEEKDAYS, hm(15, 30), hm(19))])
        self.assertEqual(parse("MON-FRI:11-2pm"), [(WEEKDAYS, hm(11), hm(14))])

    def test_midnight_and_noon(self):
        self.assertEqual(parse("DAILY:MIDNIGHT-5:30 AM"), [(ALL_DAYS, 0, hm(5, 30))])
        sched = parse("MON-FRI:8am-5:30pm ,SAT:8am-12noon ")
        self.assertTrue(is_active(sched, SAT, hm(11, 59)))
        self.assertFalse(is_active(sched, SAT, hm(12)))
        self.assertTrue(is_active(sched, FRI, hm(17, 29)))
        self.assertFalse(is_active(sched, SUN, hm(9)))

    def test_no_days_means_daily(self):
        self.assertEqual(parse(":10pm-midnight ,:midnight-6am"), [(ALL_DAYS, 0, hm(6)), (ALL_DAYS, hm(22), 1440)])

    def test_two_day_groups(self):
        sched = parse("MON-FRI:4:00PM-7:00PM ,SUN:5:00AM-3:00PM ")
        self.assertTrue(is_active(sched, MON, hm(17)))
        self.assertTrue(is_active(sched, SUN, hm(10)))
        self.assertFalse(is_active(sched, SAT, hm(10)))

    def test_special_values(self):
        self.assertEqual(parse("ALL OTHER TIMES:- "), OTHER_TIMES)
        self.assertEqual(parse("AT ALL TIMES"), ALWAYS)
        self.assertIsNone(parse(""))
        self.assertIsNone(parse(None))
        self.assertIsNone(parse("null:10 PM-10 PM"))
        self.assertIsNone(parse("MON-FRI:7-9"))


class ParseClearways(unittest.TestCase):
    def test_times_before_days(self):
        self.assertEqual(parse("7AM-9AM  4PM-7PM MON-FRI"),
                         [(WEEKDAYS, hm(7), hm(9)), (WEEKDAYS, hm(16), hm(19))])

    def test_short_day_names(self):
        self.assertEqual(parse("4PM-7PM M-F"), [(WEEKDAYS, hm(16), hm(19))])

    def test_daily_and_mon_sat(self):
        self.assertEqual(parse("7AM-7PM DAILY"), [(ALL_DAYS, hm(7), hm(19))])
        self.assertEqual(parse("7AM-11AM  2PM-7PM MON-SAT"),
                         [(0b0111111, hm(7), hm(11)), (0b0111111, hm(14), hm(19))])


class Complement(unittest.TestCase):
    def test_complement_of_weekday_peak(self):
        other = complement([parse("MON-FRI:7am-9am")])
        self.assertFalse(is_active(other, TUE, hm(8)))
        self.assertTrue(is_active(other, TUE, hm(10)))
        self.assertTrue(is_active(other, SAT, hm(8)))

    def test_complement_of_nothing_is_always(self):
        self.assertEqual(complement([]), [(ALL_DAYS, 0, 1440)])

    def test_overnight_wraps_to_next_day(self):
        sched = parse("FRI:10pm-2am")
        self.assertTrue(is_active(sched, FRI, hm(23)))
        self.assertTrue(is_active(sched, SAT, hm(1)))
        self.assertFalse(is_active(sched, FRI, hm(1)))


if __name__ == "__main__":
    unittest.main()
