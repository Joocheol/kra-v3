#!/usr/bin/env python3
import csv
import gzip
import sys
import unittest
from collections import Counter

sys.setrecursionlimit(10000)

DATA = "데이터/trifecta_feasible_sets.csv.gz"
LIMIT = 1000


def count_exact(total: int, k: int, u: int, limit: int) -> int:
    """Count sorted integer vectors u>=x1>=...>=xk>=0 summing to total.

    Return at most limit+1. By Ferrers-diagram complementation the coefficient
    is symmetric around k*u/2, which substantially reduces the search target.
    """
    if total < 0 or total > k * u:
        return 0
    target = min(total, k * u - total)
    if target == 0:
        return 1
    if k <= 0 or u <= 0:
        return 0

    found = 0

    def dfs(rem: int, max_part: int, slots: int) -> None:
        nonlocal found
        if found > limit:
            return
        if rem == 0:
            found += 1
            return
        if slots <= 0 or max_part <= 0 or rem > slots * max_part:
            return
        hi = min(max_part, rem)
        lo = max(1, (rem + slots - 1) // slots)
        for x in range(hi, lo - 1, -1):
            rem2 = rem - x
            if rem2 > (slots - 1) * x:
                continue
            dfs(rem2, x, slots - 1)
            if found > limit:
                return

    dfs(target, u, k)
    return min(found, limit + 1)


def count_interval(lo: int, hi: int, k: int, u: int, limit: int = LIMIT) -> int:
    """Count sorted vectors whose total lies anywhere in [lo, hi], truncated."""
    lo = max(0, lo)
    hi = min(k * u, hi)
    if lo > hi:
        return 0
    peak = k * u // 2
    center = min(max(peak, lo), hi)
    total_count = 0

    def add(r: int) -> bool:
        nonlocal total_count
        remaining = limit - total_count
        c = count_exact(r, k, u, remaining)
        total_count += c
        return total_count > limit

    if add(center):
        return limit + 1
    d = 1
    while center - d >= lo or center + d <= hi:
        if center - d >= lo and add(center - d):
            return limit + 1
        if center + d <= hi and add(center + d):
            return limit + 1
        d += 1
    return total_count


def bucket(n: int) -> str:
    if n == 1:
        return "1"
    if n <= 10:
        return "2-10"
    if n <= 100:
        return "11-100"
    if n <= 1000:
        return "101-1000"
    return ">1000"


class SortedPartition2017(unittest.TestCase):
    def test_2017_sorted_partition_identification(self):
        with gzip.open(DATA, "rt", encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh)
                    if r["year"] == "2017" and int(r["capped_cells"]) > 0]

        self.assertEqual(len(rows), 2404)
        strict_rows = [r for r in rows if r["strict_feasible"] == "1"]
        self.assertEqual(len(strict_rows), 1660)

        strict_counts = Counter()
        strict_detail = []
        for r in strict_rows:
            k = int(r["capped_cells"])
            u = int(r["cap_ticket_upper"])
            lo = int(r["feasible_residual_min"])
            hi = int(r["feasible_residual_max"])
            n = count_interval(lo, hi, k, u)
            strict_counts[bucket(n)] += 1
            if n <= LIMIT:
                strict_detail.append((n, r["race_id"], int(r["sales_won"]), k, u, lo, hi))

        combined_counts = Counter()
        nonstrict_relaxed_detail = []
        for r in rows:
            k = int(r["capped_cells"])
            u = int(r["cap_ticket_upper"])
            if r["strict_feasible"] == "1":
                lo = int(r["feasible_residual_min"])
                hi = int(r["feasible_residual_max"])
            else:
                self.assertEqual(r["relaxed_feasible"], "1")
                lo = int(r["relaxed_residual_min"])
                hi = int(r["relaxed_residual_max"])
            n = count_interval(lo, hi, k, u)
            combined_counts[bucket(n)] += 1
            if r["strict_feasible"] != "1" and n <= LIMIT:
                nonstrict_relaxed_detail.append((n, r["race_id"], int(r["sales_won"]), k, u, lo, hi))

        print("SORTED_PARTITION_2017_SUMMARY")
        print(f"capped_races={len(rows)} strict_races={len(strict_rows)} nonstrict_races={len(rows)-len(strict_rows)}")
        print("strict_counts=" + ",".join(f"{b}:{strict_counts[b]}" for b in ["1","2-10","11-100","101-1000",">1000"]))
        print("combined_strict_or_relaxed_counts=" + ",".join(f"{b}:{combined_counts[b]}" for b in ["1","2-10","11-100","101-1000",">1000"]))
        print(f"strict_exact_le_1000={len(strict_detail)}")
        for item in sorted(strict_detail):
            n, race_id, sales, k, u, lo, hi = item
            print(f"STRICT_DETAIL race={race_id} candidates={n} sales={sales} k={k} U={u} R={lo}-{hi}")
        print(f"nonstrict_relaxed_exact_le_1000={len(nonstrict_relaxed_detail)}")
        for item in sorted(nonstrict_relaxed_detail):
            n, race_id, sales, k, u, lo, hi = item
            print(f"RELAXED_DETAIL race={race_id} candidates={n} sales={sales} k={k} U={u} R={lo}-{hi}")

        self.assertEqual(sum(strict_counts.values()), 1660)
        self.assertEqual(sum(combined_counts.values()), 2404)
        self.fail("intentional temporary diagnostic stop after result output")


if __name__ == "__main__":
    unittest.main(verbosity=2)
