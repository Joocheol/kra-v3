import math
import unittest

from analyze_outcome_evaluation import (
    accounting_outcome_interval,
    harville_trifecta,
    score_distribution,
    state_uniform,
)
from check_coherence import norm


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

    def test_harville_first_place_marginal_equals_normalized_win_price(self):
        odds = {1: 2.0, 2: 3.0, 3: 4.0, 4: 5.0}
        distribution = harville_trifecta(odds)
        expected = norm({horse: 1 / value for horse, value in odds.items()})
        for horse, probability in expected.items():
            marginal = sum(
                value for (first, _second, _third), value in distribution.items()
                if first == horse
            )
            self.assertAlmostEqual(marginal, probability)

    def test_capped_realized_state_accounting_lower_bound_can_bind(self):
        outcome = (1, 2, 3)
        odds = {
            outcome: 9999.9,
            (1, 3, 2): 9999.9,
            (2, 1, 3): 9999.9,
        }
        race = {
            "race_id": "synthetic",
            "sales": {"삼쌍승식": "2,000"},
        }
        info = {
            "cap_upper": 4,
            "residual_min": 10,
            "residual_max": 11,
        }
        lower, upper, capped = accounting_outcome_interval(
            race, odds, info, outcome
        )
        self.assertTrue(capped)
        # With C=3 and N=4, if at least 10 tickets occupy capped cells,
        # the realized cell must carry at least 10 - 2*4 = 2 tickets.
        self.assertAlmostEqual(lower, 2 / 20)
        self.assertAlmostEqual(upper, 4 / 20)


if __name__ == "__main__":
    unittest.main()
