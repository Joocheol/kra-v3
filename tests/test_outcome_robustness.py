import itertools
import unittest

from analyze_outcome_evaluation import harville_trifecta
from analyze_outcome_robustness import (
    _max_sumsq,
    _min_sumsq,
    discounted_harville_trifecta,
    exacta_anchored_trifecta,
    poisson_binomial_interval,
)


class OutcomeRobustnessTests(unittest.TestCase):
    def test_discount_lambda_one_equals_harville(self):
        odds = {1: 2.1, 2: 3.2, 3: 4.7, 4: 8.3}
        ordinary = harville_trifecta(odds)
        discounted = discounted_harville_trifecta(odds, 1.0)
        self.assertEqual(set(ordinary), set(discounted))
        for state in ordinary:
            self.assertAlmostEqual(ordinary[state], discounted[state], places=14)

    def test_dual_lambda_one_equals_harville(self):
        odds = {1: 2.1, 2: 3.2, 3: 4.7, 4: 8.3}
        ordinary = harville_trifecta(odds)
        dual = discounted_harville_trifecta(odds, 1.0, 1.0)
        for state in ordinary:
            self.assertAlmostEqual(ordinary[state], dual[state], places=14)

    def test_discounted_first_place_marginal_is_unchanged(self):
        odds = {1: 2.1, 2: 3.2, 3: 4.7, 4: 8.3}
        discounted = discounted_harville_trifecta(odds, 0.73)
        inv = {horse: 1 / value for horse, value in odds.items()}
        total = sum(inv.values())
        for horse in odds:
            marginal = sum(p for (a, _, _), p in discounted.items() if a == horse)
            self.assertAlmostEqual(marginal, inv[horse] / total, places=14)

    def test_exacta_anchor_has_complete_support(self):
        win = {1: 2.1, 2: 3.2, 3: 4.7, 4: 8.3}
        exacta = {pair: float(i + 2) for i, pair in enumerate(itertools.permutations(win, 2))}
        distribution = exacta_anchored_trifecta(exacta, win)
        self.assertEqual(len(distribution), 24)
        self.assertAlmostEqual(sum(distribution.values()), 1.0, places=14)

    def test_poisson_binomial_two_fair_coins(self):
        mean, low, high, pvalue = poisson_binomial_interval([.5, .5], 1)
        self.assertEqual((mean, low, high, pvalue), (1.0, 0, 2, 1.0))

    def test_sumsq_extrema_match_exhaustive_integer_boxes(self):
        n, total, lo, hi = 4, 9, 1, 4
        values = [x for x in itertools.product(range(lo, hi + 1), repeat=n) if sum(x) == total]
        sums = [sum(v * v for v in row) for row in values]
        self.assertEqual(_min_sumsq(n, total, lo, hi), min(sums))
        self.assertEqual(_max_sumsq(n, total, lo, hi), max(sums))


if __name__ == "__main__":
    unittest.main()
