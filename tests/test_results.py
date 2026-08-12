from decimal import Decimal
import unittest

from kra.results import (
    detail_url,
    parse_winning_dividends,
    parse_winning_trifecta,
    ticket_candidates,
)
from collect_winning_payouts import _could_pay
from kra.feasible import (
    capped_ticket_upper,
    constrained_capped_bounds,
    displayed_ticket_interval,
)


FIXTURE = """
<table>
  <caption>배당률의 정보를 제공하는 표</caption>
  <tbody>
    <tr><th rowspan="2">배당률</th>
      <td>단승식: &#9326; 56.0</td>
      <td>복연승식: &#9326;&#9314; 105.5 &#9326;&#9315; 773.5</td></tr>
    <tr><td>삼쌍승식: &#9326;&#9314;&#9315; 391736.8</td><td>&nbsp;</td></tr>
  </tbody>
</table>
"""


class ResultsTest(unittest.TestCase):
    def test_parse_all_entries(self):
        got = parse_winning_dividends(FIXTURE)
        self.assertEqual([x.pool for x in got], ["단승식", "복연승식", "복연승식", "삼쌍승식"])
        self.assertEqual(got[-1].combination, (15, 3, 4))
        self.assertEqual(got[-1].odds, Decimal("391736.8"))

    def test_parse_trifecta_only(self):
        got = parse_winning_trifecta(FIXTURE)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].combination, (15, 3, 4))

    def test_record_payout_identifies_seven_tickets(self):
        got = ticket_candidates(375_638_000, Decimal("391736.8"))
        self.assertEqual(list(got), [7])

    def test_detail_url(self):
        url = detail_url("2017-06-11_3_05")
        self.assertIn("meet=3", url)
        self.assertIn("realRcDate=20170611", url)
        self.assertIn("realRcNo=5", url)

    def test_place_pays_two_with_seven_finishers(self):
        arrival = [8, 4, 3, 7, 1, 2, 6]
        self.assertTrue(_could_pay("연승식", (4,), arrival))
        self.assertFalse(_could_pay("연승식", (3,), arrival))

    def test_place_pays_three_with_eight_finishers(self):
        arrival = [8, 4, 3, 7, 1, 2, 6, 5]
        self.assertTrue(_could_pay("연승식", (3,), arrival))

    def test_displayed_interval_point_identifies_seven_tickets(self):
        got = displayed_ticket_interval(375_638_000, Decimal("391736.8"))
        self.assertEqual(list(got), [7])

    def test_cap_includes_zero_plus_positive_grid(self):
        # 2016-06-10 제주 1경주: K/c is between 21 and 22.
        self.assertEqual(capped_ticket_upper(29_747_400), 21)

    def test_zero_bounds_are_sharp(self):
        got = constrained_capped_bounds(10, 3, 4, 7)
        self.assertIsNotNone(got)
        self.assertEqual(got.min_zero_cells, 3)  # at most 7 positive cells
        self.assertEqual(got.max_zero_cells, 8)  # 4 tickets fit in 2 cells
        self.assertEqual((got.cell_ticket_min, got.cell_ticket_max), (0, 3))

    def test_infeasible_residual_is_rejected(self):
        self.assertIsNone(constrained_capped_bounds(2, 3, 7, 9))


if __name__ == "__main__":
    unittest.main()
