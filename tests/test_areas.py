"""Tests for the area helpers in the build. Run: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from build import NAME_CHAR_PX, NAME_LINE_PX, _name_box, _stitch  # noqa: E402


class Stitch(unittest.TestCase):
    def test_joins_edges_into_one_path_in_order(self):
        lines = _stitch([((1, 0), (2, 0)), ((0, 0), (1, 0)), ((2, 0), (3, 0))])
        self.assertEqual(len(lines), 1)
        self.assertIn(lines[0], ([(0, 0), (1, 0), (2, 0), (3, 0)], [(3, 0), (2, 0), (1, 0), (0, 0)]))

    def test_two_suburbs_without_their_shared_border_make_one_loop(self):
        a = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        b = [(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)]
        shared = frozenset(((1, 0), (1, 1)))
        edges = {frozenset(e) for ring in (a, b) for e in zip(ring, ring[1:])} - {shared}
        lines = _stitch([tuple(e) for e in edges])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][0], lines[0][-1])  # closed
        self.assertEqual(len(lines[0]), 7)           # the six outer edges

    def test_lines_break_where_three_borders_meet(self):
        lines = _stitch([((0, 0), (1, 0)), ((0, 0), (-1, 0)), ((0, 0), (0, 1))])
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(len(line) == 2 for line in lines))


class NameBox(unittest.TestCase):
    def test_short_name_is_one_line(self):
        w, h = _name_box("CBD")
        self.assertEqual(h, NAME_LINE_PX / 2)
        self.assertAlmostEqual(w, 3 * NAME_CHAR_PX / 2)

    def test_long_name_wraps_onto_two_lines(self):
        w, h = _name_box("Fortitude Valley")
        self.assertEqual(h, NAME_LINE_PX)
        self.assertAlmostEqual(w, len("FORTITUDE") * NAME_CHAR_PX / 2)


if __name__ == "__main__":
    unittest.main()
