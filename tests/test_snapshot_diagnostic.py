from decimal import Decimal
import unittest

from diagnose_snapshot_mismatch import candidate_totals_for_cell, explain_race
from kra.feasible import displayed_ticket_interval


class SnapshotDiagnosticTests(unittest.TestCase):
    def test_candidate_totals_match_direct_inverse(self):
        for value, lo, hi in [
            (Decimal("730.0"), 990, 1010),
            (Decimal("123.4"), 500, 700),
            (Decimal("7.3"), 900, 1100),
        ]:
            expected = {
                total for total in range(lo, hi + 1)
                if displayed_ticket_interval(total * 100, value)
            }
            self.assertEqual(candidate_totals_for_cell(value, lo, hi), expected)

    def test_single_earlier_snapshot_can_explain_all_cells(self):
        # At T'=1000, n=1 displays 730.0 and n=100 displays 7.3.
        # The recorded final T=1001 makes 730.0 incompatible while 7.3 remains
        # compatible.  The diagnostic must recover the common earlier T'.
        best, bad, candidates = explain_race(
            [Decimal("730.0"), Decimal("7.3")], 1001, 100
        )
        self.assertEqual(best, 1000)
        self.assertEqual(bad, 1)
        self.assertGreaterEqual(candidates, 1)

    def test_incompatible_cells_need_one_common_snapshot(self):
        # These two high dividends require disjoint nearby totals.
        best, bad, candidates = explain_race(
            [Decimal("730.0"), Decimal("735.0")], 1001, 100
        )
        self.assertIsNone(best)
        self.assertEqual(bad, 2)
        self.assertEqual(candidates, 0)


if __name__ == "__main__":
    unittest.main()
