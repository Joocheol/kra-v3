import math
import unittest

from analyze_outcome_evaluation import harville_trifecta, score_distribution, state_uniform


class OutcomeEvaluationTests(unittest.TestCase):
    def test_uniform_multiclass_brier(self):
        keys = {(1, 2, 3), (1, 3, 2), (2, 1, 3), (2, 3, 1)}
        distribution = state_uniform(keys)
        realized, zero, nll, brier, rank = score_distribution(
            distribution, (1, 2, 3)
        )
        self.assertFalse(zero)
        self.assertAlmostEqual(realized, 0.25)
        self.assertAlmostEqual(nll, math.log(4))
        self.assertAlmostEqual(brier, 0.75)
        self.assertAlmostEqual(rank, 0.625)

    def test_zero_probability_is_reported_without_log_epsilon(self):
        distribution = {(1, 2, 3): 0.0, (1, 3, 2): 1.0}
        realized, zero, nll, brier, rank = score_distribution(
            distribution, (1, 2, 3)
        )
        self.assertEqual(realized, 0.0)
        self.assertTrue(zero)
        self.assertIsNone(nll)
        self.assertAlmostEqual(brier, 2.0)
        self.assertEqual(rank, 1.0)

    def test_harville_joint_is_normalized_and_complete(self):
        odds = {1: 2.0, 2: 3.0, 3: 4.0, 4: 5.0}
        distribution = harville_trifecta(odds)
        self.assertEqual(len(distribution), 24)
        self.assertAlmostEqual(sum(distribution.values()), 1.0)
        self.assertTrue(all(value > 0 for value in distribution.values()))


if __name__ == "__main__":
    unittest.main()
