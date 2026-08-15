import unittest

import numpy as np

from kra.rank_profile import (
    CLASS_NAMES,
    assign_ranked_counts,
    bounded_rank_allocation,
    bounded_weight_allocation,
    fit_rank_profile_mixture,
    hidden_total_interval,
    partial_class_probabilities,
    rank_profile,
    tail_rank_scores,
)


class RankProfileTests(unittest.TestCase):
    def test_rank_profile_is_scale_free(self):
        counts = np.asarray([20, 10, 5, 2, 1])
        np.testing.assert_allclose(rank_profile(counts), rank_profile(7 * counts))

    def test_three_types_are_ordered_by_head_concentration(self):
        diffuse = np.tile(np.asarray([8, 7, 6, 5, 4, 3, 2, 1]), (8, 1))
        middle = np.tile(np.asarray([20, 9, 7, 5, 3, 2, 1, 1]), (8, 1))
        concentrated = np.tile(np.asarray([50, 8, 5, 3, 2, 1, 1, 1]), (8, 1))
        profiles = np.stack([rank_profile(row) for row in np.vstack([
            diffuse, middle, concentrated,
        ])])
        fitted = fit_rank_profile_mixture(profiles)
        self.assertEqual(CLASS_NAMES, ("diffuse", "intermediate", "concentrated"))
        head = fitted.centroids[:, fitted.grid <= 0.10].mean(axis=1)
        self.assertTrue(np.all(np.diff(head) > 0))
        self.assertEqual(fitted.class_sizes.sum(), len(profiles))

    def test_partial_head_prefers_matching_profile(self):
        rows = []
        for scale in range(1, 10):
            rows.append(rank_profile(scale * np.asarray([9, 8, 7, 6, 5, 4, 3, 2])))
            rows.append(rank_profile(scale * np.asarray([22, 10, 7, 5, 3, 2, 1, 1])))
            rows.append(rank_profile(scale * np.asarray([55, 8, 5, 3, 2, 1, 1, 1])))
        fitted = fit_rank_profile_mixture(np.stack(rows))
        probabilities, _ = partial_class_probabilities(
            np.asarray([55, 8, 5, 3]),
            total_cells=8,
            total_tickets=76,
            mixture=fitted,
        )
        self.assertEqual(int(np.argmax(probabilities)), 2)

    def test_bounded_rank_allocation_preserves_total_and_order(self):
        counts = bounded_rank_allocation(17, np.asarray([9.0, 4.0, 2.0, 1.0]), 6)
        self.assertEqual(int(counts.sum()), 17)
        self.assertLessEqual(int(counts.max()), 6)
        self.assertTrue(np.all(np.diff(counts) <= 0))

    def test_bounded_weight_allocation_accepts_cell_specific_limits(self):
        counts = bounded_weight_allocation(
            7,
            np.asarray([10.0, 2.0, 1.0]),
            np.asarray([1, 5, 5]),
        )
        self.assertEqual(int(counts.sum()), 7)
        self.assertLessEqual(int(counts[0]), 1)
        self.assertTrue(np.all(counts <= np.asarray([1, 5, 5])))

    def test_bounded_weight_allocation_handles_zero_weight_capacity(self):
        counts = bounded_weight_allocation(
            7,
            np.asarray([1.0, 0.0, 0.0]),
            np.asarray([1, 5, 5]),
        )
        self.assertEqual(int(counts.sum()), 7)
        self.assertTrue(np.all(counts <= np.asarray([1, 5, 5])))

    def test_hidden_total_interval_uses_only_observed_bounds(self):
        interval = hidden_total_interval(
            25,
            np.asarray([7, 8]),
            np.asarray([9, 10]),
            np.asarray([3, 4, 5]),
        )
        self.assertEqual(interval, (6, 10))

    def test_hidden_total_interval_rejects_infeasible_inputs(self):
        with self.assertRaises(ValueError):
            hidden_total_interval(
                30,
                np.asarray([7, 8]),
                np.asarray([9, 10]),
                np.asarray([3, 4]),
            )

    def test_assign_ranked_counts_respects_named_cell_scores(self):
        assigned = assign_ranked_counts(
            np.asarray([7, 4, 1]), np.asarray([0.2, 0.9, 0.4])
        )
        np.testing.assert_array_equal(assigned, np.asarray([1, 7, 4]))

    def test_tail_scores_match_hidden_cell_count(self):
        profiles = np.stack([
            rank_profile(np.asarray(row))
            for row in (
                [9, 8, 7, 6, 5, 4, 3, 2],
                [22, 10, 7, 5, 3, 2, 1, 1],
                [55, 8, 5, 3, 2, 1, 1, 1],
            )
            for _ in range(4)
        ])
        fitted = fit_rank_profile_mixture(profiles)
        scores = tail_rank_scores(fitted, 1, total_cells=8, visible_cells=3)
        self.assertEqual(len(scores), 5)
        self.assertTrue(np.all(np.diff(scores) <= 0))


if __name__ == "__main__":
    unittest.main()
