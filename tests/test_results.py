from decimal import Decimal
from decimal import ROUND_HALF_UP
import csv
import gzip
from itertools import product, permutations
import pathlib
import tempfile
import unittest

from kra.results import (
    detail_url,
    parse_winning_dividends,
    parse_winning_trifecta,
    ticket_candidates,
)
from collect_winning_payouts import _could_pay, _grid_combination
from analyze_feasible_sets import build_rows, scan_grids, write_csv_gz
from analyze_masked_reconstruction import (
    ModelUnavailable,
    bounded_integer_projection,
    model_scores,
    proportional_integer_allocation,
)
from analyze_sparse_baseline import occupancy_moments
from analyze_dirichlet_multinomial import zero_probability
from analyze_cross_market import marginalize, metric_row
from kra.feasible import (
    capped_ticket_upper,
    constrained_capped_bounds,
    displayed_ticket_interval,
    displayed_total_interval,
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

    def test_place_uses_starters_not_finishers(self):
        arrival = [8, 4, 3, 7, 1, 2, 6]
        self.assertTrue(_could_pay("연승식", (3,), arrival, starters=8))

    def test_displayed_interval_point_identifies_seven_tickets(self):
        got = displayed_ticket_interval(375_638_000, Decimal("391736.8"))
        self.assertEqual(list(got), [7])

    def test_total_interval_is_exact_inverse(self):
        for total in range(1, 500):
            for odds in (Decimal("1.0"), Decimal("7.3"), Decimal("99.9")):
                for rounding in ("half_up", "half_even", "floor"):
                    tickets = displayed_ticket_interval(
                        100 * total, odds, rounding=rounding
                    )
                    for n in range(1, 80):
                        totals = displayed_total_interval(
                            n, odds, rounding=rounding
                        )
                        self.assertEqual(n in tickets, total in totals)

    def test_cap_includes_zero_plus_positive_grid(self):
        # 2016-06-10 제주 1경주: K/c is between 21 and 22.
        self.assertEqual(capped_ticket_upper(29_747_400), 21)

    def test_display_cap_boundary_is_wider_than_strict_true_odds(self):
        self.assertEqual(capped_ticket_upper(9_588_900), 7)
        self.assertEqual(
            capped_ticket_upper(9_588_900, definition="strict_true"), 6
        )

    def test_pool_multiplier_divides_ticket_grid(self):
        base = displayed_ticket_interval(3_000_000, Decimal("73.0"))
        qplace = displayed_ticket_interval(
            3_000_000, Decimal("73.0"), pool_multiplier=3
        )
        self.assertEqual(base.start, 300)
        self.assertEqual(qplace.start, 100)

    def test_zero_bounds_are_sharp(self):
        got = constrained_capped_bounds(10, 3, 4, 7)
        self.assertIsNotNone(got)
        self.assertEqual(got.min_zero_cells, 3)  # at most 7 positive cells
        self.assertEqual(got.max_zero_cells, 8)  # 4 tickets fit in 2 cells
        self.assertEqual((got.cell_ticket_min, got.cell_ticket_max), (0, 3))

    def test_infeasible_residual_is_rejected(self):
        self.assertIsNone(constrained_capped_bounds(2, 3, 7, 9))

    def test_zero_bounds_match_exhaustive_integer_allocations(self):
        for cells in range(1, 5):
            for upper in range(0, 4):
                capacity = cells * upper
                for lo in range(-1, capacity + 2):
                    for hi in range(lo, capacity + 2):
                        allocations = [
                            values for values in product(range(upper + 1), repeat=cells)
                            if lo <= sum(values) <= hi
                        ]
                        got = constrained_capped_bounds(cells, upper, lo, hi)
                        if not allocations:
                            self.assertIsNone(got)
                            continue
                        self.assertIsNotNone(got)
                        zero_counts = [values.count(0) for values in allocations]
                        cell_values = [value for values in allocations for value in values]
                        self.assertEqual(got.min_zero_cells, min(zero_counts))
                        self.assertEqual(got.max_zero_cells, max(zero_counts))
                        self.assertEqual(got.cell_ticket_min, min(cell_values))
                        self.assertEqual(got.cell_ticket_max, max(cell_values))

    def test_bounded_integer_projection_preserves_boxes_and_sum(self):
        target = __import__("numpy").array([1.2, 4.8, 3.1])
        lower = __import__("numpy").array([1, 2, 0])
        upper = __import__("numpy").array([2, 5, 4])
        got = bounded_integer_projection(target, lower, upper, 8)
        self.assertEqual(int(got.sum()), 8)
        self.assertTrue(((got >= lower) & (got <= upper)).all())

    def test_proportional_allocation_preserves_total(self):
        np = __import__("numpy")
        got, probabilities = proportional_integer_allocation(
            17, np.array([1.0, 2.0, 3.0])
        )
        self.assertEqual(int(got.sum()), 17)
        self.assertAlmostEqual(float(probabilities.sum()), 1.0)

    def test_proportional_allocation_breaks_near_ties_by_input_order(self):
        np = __import__("numpy")
        got, _ = proportional_integer_allocation(
            1, np.array([1.0, 1.0 + 1e-13])
        )
        self.assertEqual(got.tolist(), [1, 0])

    def test_auxiliary_model_rejects_censored_source_pool(self):
        np = __import__("numpy")
        with self.assertRaises(ModelUnavailable):
            model_scores(
                "win_harville",
                [(1, 2, 3), (1, 3, 2)],
                np.array([2, 1]),
                np.array([True, False]),
                np.array([False, True]),
                [1, 2, 3],
                cross_pool={"단승식": {(1,): 2.0, (2,): 9999.9, (3,): 4.0}},
            )

    def test_uniform_occupancy_moments_match_enumeration(self):
        for cells in range(1, 5):
            for tickets in range(0, 5):
                outcomes = list(product(range(cells), repeat=tickets))
                zeros = [cells - len(set(outcome)) for outcome in outcomes]
                mean = sum(zeros) / len(zeros)
                variance = sum((value - mean) ** 2 for value in zeros) / len(zeros)
                got_mean, got_variance = occupancy_moments(cells, tickets)
                self.assertAlmostEqual(got_mean, mean)
                self.assertAlmostEqual(got_variance, variance)

    def test_dm_zero_probability_converges_to_multinomial(self):
        cells, tickets = 7, 9
        expected = (1 - 1 / cells) ** tickets
        self.assertAlmostEqual(
            zero_probability(cells, tickets, 1e8), expected, places=5
        )

    def test_trifecta_marginals_preserve_probability(self):
        table = {
            (1, 2, 3): .4,
            (2, 1, 3): .3,
            (3, 2, 1): .3,
        }
        got = marginalize(table)
        for target in ("win", "exacta", "quinella", "trio"):
            self.assertAlmostEqual(sum(got[target].values()), 1.0)
        self.assertAlmostEqual(got["quinella"][frozenset((1, 2))], .7)

    def test_swapping_second_and_third_is_an_orientation_falsification(self):
        table = {
            (1, 2, 3): .4,
            (2, 1, 3): .3,
            (3, 2, 1): .3,
        }
        original = marginalize(table)
        swapped = marginalize({(a, c, b): p for (a, b, c), p in table.items()})
        self.assertEqual(original["win"], swapped["win"])
        self.assertEqual(original["trio"], swapped["trio"])
        self.assertNotEqual(original["exacta"], swapped["exacta"])
        self.assertNotEqual(original["quinella"], swapped["quinella"])

    def test_cross_market_metric_rejects_mismatched_support(self):
        truth = {1: .6, 2: .4}
        prediction = {1: .5, 2: .4, 3: .1}
        self.assertIsNone(metric_row(
            "race", "2025", "residual_mid", "win", "model",
            truth, prediction,
        ))

    def test_all_grid_axis_mappings(self):
        common = {"row_header": "3", "col_header": "2", "page_variant": "1"}
        self.assertEqual(
            _grid_combination({**common, "page_key": "Both", "col_group": ""}),
            ("쌍승식", (2, 3)),
        )
        self.assertEqual(
            _grid_combination({**common, "page_key": "Bc", "col_group": ""}),
            ("복연승식", (2, 3)),
        )
        self.assertEqual(
            _grid_combination({**common, "page_key": "3Bc", "col_group": ""}),
            ("삼복승식", (1, 2, 3)),
        )
        self.assertEqual(
            _grid_combination({**common, "page_key": "3Both", "col_group": ""}),
            ("삼쌍승식", (1, 2, 3)),
        )

    def test_real_kra_detail_page_fixture(self):
        path = pathlib.Path("데이터/winning_payout_html/2017-06-11_3_05.html")
        raw = path.read_bytes()
        html = raw.decode("cp949")
        payouts = parse_winning_dividends(html)
        self.assertIn(
            ("삼쌍승식", (15, 3, 4), Decimal("391736.8")),
            [(p.pool, p.combination, p.odds) for p in payouts],
        )

    def test_synthetic_grid_end_to_end_and_deterministic_gzip(self):
        race_id = "2026-01-01_1_01"
        sales = 100_000
        race = {
            "race_id": race_id,
            "date": "2026-01-01",
            "meet": 1,
            "horses": [1, 2, 3, 4],
            "scratched": [],
            "sales": {"삼쌍승식": f"{sales}원", "총매출액": f"{sales}원"},
        }
        combos = list(permutations(race["horses"], 3))
        counts = [0] + [43] * 22 + [54]
        self.assertEqual(sum(counts), sales // 100)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            part = root / "cells/page_key=3Both/2026-01.csv.gz"
            part.parent.mkdir(parents=True)
            fields = [
                "race_id", "page_key", "page_variant", "section", "row", "col",
                "row_header", "col_group", "col_header", "cell_raw", "rowspan",
                "colspan", "spanned",
            ]
            with gzip.open(part, "wt", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                for combo, count in zip(combos, counts):
                    odds = (
                        "9999.9" if count == 0 else
                        str((Decimal("730") / count).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                    )
                    writer.writerow({
                        "race_id": race_id, "page_key": "3Both",
                        "page_variant": combo[0], "section": "body", "row": combo[2],
                        "col": combo[1], "row_header": combo[2], "col_group": "",
                        "col_header": combo[1], "cell_raw": odds, "rowspan": 1,
                        "colspan": 1, "spanned": 0,
                    })
            totals = scan_grids(root, {race_id: race})
            rows = build_rows({race_id: race}, totals)
            self.assertEqual(rows[0]["observed_numeric_cells"], 24)
            self.assertEqual(rows[0]["min_unbet_cells"], 1)
            self.assertEqual(rows[0]["max_unbet_cells"], 1)
            first, second = root / "first.csv.gz", root / "second.csv.gz"
            write_csv_gz(first, rows)
            write_csv_gz(second, rows)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
