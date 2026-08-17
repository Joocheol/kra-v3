from __future__ import annotations

import unittest
from decimal import Decimal

from collect_openapi_payouts import (
    expected_combinations,
    find_missing_candidates,
    year_range,
    normalize_rows,
    parse_odds,
)


class ParseOddsTests(unittest.TestCase):
    def test_parses_multiple_place_payouts(self) -> None:
        self.assertEqual(
            parse_odds("③-2.7  ⑮-14.4  ④-29.4", "연승식"),
            [((3,), Decimal("2.7")), ((15,), Decimal("14.4")), ((4,), Decimal("29.4"))],
        )

    def test_parses_uncapped_trifecta(self) -> None:
        self.assertEqual(
            parse_odds("⑮③④-391736.8", "삼쌍승식"),
            [((15, 3, 4), Decimal("391736.8"))],
        )

    def test_year_range(self) -> None:
        self.assertEqual(year_range(2022, 2025), [2022, 2023, 2024, 2025])


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.race = {
            "race_id": "2017-06-11_3_05",
            "date": "2017-06-11",
            "meet_name": "부경",
            "race_no": 5,
            "n_registered": 16,
            "scratched": [],
            "arrival": [15, 3, 4, 2],
        }

    def test_expected_combinations_all_pools(self) -> None:
        self.assertEqual(expected_combinations(self.race, "단승식"), [(15,)])
        self.assertEqual(expected_combinations(self.race, "연승식"), [(15,), (3,), (4,)])
        self.assertEqual(expected_combinations(self.race, "복승식"), [(3, 15)])
        self.assertEqual(expected_combinations(self.race, "쌍승식"), [(15, 3)])
        self.assertEqual(expected_combinations(self.race, "복연승식"), [(3, 15), (4, 15), (3, 4)])
        self.assertEqual(expected_combinations(self.race, "삼복승식"), [(3, 4, 15)])
        self.assertEqual(expected_combinations(self.race, "삼쌍승식"), [(15, 3, 4)])

    def test_normalization_recovers_seven_trifecta_tickets(self) -> None:
        rows, payouts = normalize_rows([{
            "amt": 375638000,
            "meet": 3,
            "odds": "⑮③④-391736.8",
            "pool": "삼쌍",
            "rcDate": 20170611,
            "rcNo": 5,
        }])
        self.assertEqual(rows[0]["max_odds"], Decimal("391736.8"))
        self.assertEqual(payouts[0]["ticket_count_exact"], 7)

    def test_absent_expected_place_is_candidate(self) -> None:
        rows, payouts = normalize_rows([{
            "amt": 1000000,
            "meet": 3,
            "odds": "⑮-2.0  ③-3.0",
            "pool": "연식",
            "rcDate": 20170611,
            "rcNo": 5,
        }])
        missing = find_missing_candidates([self.race], rows, payouts)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["expected_combination"], "4")
        self.assertEqual(missing[0]["candidate_class"], "expected_combination_unpaid")


if __name__ == "__main__":
    unittest.main()
