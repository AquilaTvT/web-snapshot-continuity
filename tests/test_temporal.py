"""Exhaustive finite-model checks plus independent certificate corruption tests."""

import itertools
import unittest

from src.temporal import (
    BlockedSegment, all_k_subsets_coexist, bridge_error, common_times,
    intervals_from_revisions, minimal_conflict, noncoexistence_certificate,
    normalize, return_obstruction, sparse_ambiguity_fixture, verify_noncoexistence,
)


def cells(mask, width):
    return normalize((i, i + 1) for i in range(width) if mask & (1 << i))


class TemporalTests(unittest.TestCase):
    def test_exhaustive_three_resources_four_cells(self):
        for masks in itertools.product(range(16), repeat=3):
            family = [cells(mask, 4) for mask in masks]
            expected = cells(masks[0] & masks[1] & masks[2], 4)
            self.assertEqual(common_times(family, (0, 4)), expected)
            if not expected:
                cert = noncoexistence_certificate(family, (0, 4))
                self.assertTrue(verify_noncoexistence(family, (0, 4), cert))

    def test_unbounded_witness_order(self):
        for size in range(2, 13):
            family, window = return_obstruction(size)
            self.assertFalse(common_times(family, window))
            self.assertTrue(all_k_subsets_coexist(family, window, size - 1))
            self.assertEqual(minimal_conflict(family, window), tuple(range(size)))

    def test_contiguous_interval_pairwise_principle(self):
        intervals = [((a, b),) for a in range(4) for b in range(a + 1, 5)]
        for family in itertools.product(intervals, repeat=3):
            if all_k_subsets_coexist(family, (0, 4), 2):
                self.assertTrue(common_times(family, (0, 4)))

    def test_boundary_and_duplicate_input(self):
        self.assertEqual(common_times([[(0, 2), (1, 3)], [(2, 4)]], (0, 4)), ((2, 3),))
        self.assertEqual(common_times([[(0, 2)], [(2, 4)]], (0, 4)), ())
        self.assertEqual(common_times([], (0, 4)), ((0, 4),))
        self.assertEqual(common_times([[(8, 10)]], (0, 4)), ())

    def test_bad_certificates(self):
        family, window = return_obstruction(3)
        good = noncoexistence_certificate(family, window)
        self.assertFalse(verify_noncoexistence(family, window, good[:-1]))
        self.assertFalse(verify_noncoexistence(family, window, [BlockedSegment(0, 3, 0)]))
        self.assertFalse(verify_noncoexistence(family, window, [BlockedSegment(0, 3, -1)]))
        # A numerically integral float must not reach tuple indexing.
        self.assertFalse(verify_noncoexistence(family, window, [BlockedSegment(0, 3, 0.0)]))

    def test_same_samples_opposite_coexistence(self):
        fixture = sparse_ambiguity_fixture()
        for name in ("coherent_history", "incoherent_history"):
            history = fixture[name]
            for resource, time, observed in fixture["observations"]:
                actual = [value for start, value in history[resource] if start <= time][-1]
                self.assertEqual(actual, observed)
            valid = [intervals_from_revisions(revs, target, fixture["window"])
                     for revs, target in zip(history, fixture["targets"])]
            self.assertEqual(bool(common_times(valid, fixture["window"])), name == "coherent_history")

    def test_revision_return_is_not_filled(self):
        self.assertEqual(intervals_from_revisions([(0, "A"), (1, "B"), (3, "A")], "A", (0, 4)),
                         ((0, 1), (3, 4)))
        with self.assertRaises(ValueError):
            intervals_from_revisions([(1, "A")], "A", (0, 4))
        with self.assertRaises(ValueError):
            intervals_from_revisions([(0, "A"), (0, "B")], "A", (0, 4))

    def test_bridge_known_limits(self):
        self.assertEqual(bridge_error(0, 10, 5), 0)
        self.assertEqual(bridge_error(1, 10, 0), 0)
        self.assertAlmostEqual(bridge_error(100, 10, 5), 0.5)
        self.assertAlmostEqual(bridge_error(0.4, 2, 0.5), bridge_error(0.4, 2, 1.5))

    def test_non_target_and_outside_revisions_still_require_integer_time(self):
        for revisions in ([(0.0, "B")], [(0, "B"), (10.5, "B")],
                          [(-0.5, "B"), (1, "A")]):
            with self.subTest(revisions=revisions), self.assertRaises(TypeError):
                intervals_from_revisions(revisions, "A", (0, 4))


if __name__ == "__main__":
    unittest.main()
