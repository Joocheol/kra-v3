#!/usr/bin/env python3
import csv
import gzip
import sys
import unittest
from collections import Counter
from functools import lru_cache

sys.setrecursionlimit(10000)

DATA = "데이터/trifecta_feasible_sets.csv.gz"
LIMIT = 1_000_000
CAP = LIMIT + 1

# Exact unrestricted partition numbers through 60; p(61)=1,121,505 > LIMIT.
PART = [0] * 62
PART[0] = 1
for part in range(1, 62):
    for n in range(part, 62):
        PART[n] = min(CAP, PART[n] + PART[n - part])


def count_exact(total: int, k: int, u: int, limit: int = LIMIT) -> int:
    """Count partitions of total inside a k-by-u rectangle, capped at limit+1."""
    cap = limit + 1
    if total < 0 or total > k * u:
        return 0
    rem0 = min(total, k * u - total)  # complement symmetry
    if rem0 == 0:
        return 1

    @lru_cache(maxsize=None)
    def f(rem: int, m: int, s: int) -> int:
        if rem == 0:
            return 1
        if rem < 0 or m <= 0 or s <= 0 or rem > m * s:
            return 0
        m = min(m, rem)
        s = min(s, rem)
        # Transpose the Ferrers rectangle so the smaller dimension is the
        # number of recursive slots; this cuts the state space substantially.
        if s > m:
            m, s = s, m
        # When neither rectangle bound can bind, this is p(rem).
        if rem <= s:
            if rem >= 61:
                return cap
            return min(cap, PART[rem])
        a = f(rem, m - 1, s)
        if a >= cap:
            return cap
        b = f(rem - m, m, s - 1)
        return min(cap, a + b)

    return f(rem0, u, k)


def count_interval(lo: int, hi: int, k: int, u: int, limit: int = LIMIT) -> int:
    """Count sorted vectors with total in [lo,hi], capped at limit+1."""
    lo = max(0, lo)
    hi = min(k * u, hi)
    if lo > hi:
        return 0

    # Use q-binomial symmetry to put an interval entirely above the midpoint
    # onto the lower side.
    ku = k * u
    mid = ku // 2
    if lo > mid:
        lo, hi = ku - hi, ku - lo

    # If the interval contains an unrestricted coefficient p(r), r>=61,
    # that single coefficient already exceeds one million.
    free_hi = min(hi, k, u)
    if max(lo, 61) <= free_hi:
        return limit + 1

    # Start where coefficients are largest to cross the cap quickly.
    center = min(max(mid, lo), hi)
    total_count = 0

    order = [center]
    d = 1
    while center - d >= lo or center + d <= hi:
        if center - d >= lo:
            order.append(center - d)
        if center + d <= hi:
            order.append(center + d)
        d += 1

    for r in order:
        remaining = limit - total_count
        c = count_exact(r, k, u, remaining)
        total_count += c
        if total_count > limit:
            return limit + 1
    return total_count


def bucket(n: int) -> str:
    if n == 1: return "1"
    if n <= 10: return "2-10"
    if n <= 100: return "11-100"
    if n <= 1000: return "101-1000"
    if n <= 10_000: return "1001-10000"
    if n <= 100_000: return "10001-100000"
    if n <= 1_000_000: return "100001-1000000"
    return ">1000000"

BINS = ["1","2-10","11-100","101-1000","1001-10000","10001-100000","100001-1000000",">1000000"]


class FinerSortedPartition2017(unittest.TestCase):
    def test_finer_2017_counts(self):
        # Small exhaustive sanity checks for the DP.
        self.assertEqual(count_exact(5, 10, 10), 7)
        self.assertEqual(count_exact(5, 2, 10), 3)  # 5, 4+1, 3+2
        self.assertEqual(count_interval(0, 5, 1, 10), 6)

        with gzip.open(DATA, "rt", encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh)
                    if r["year"] == "2017" and int(r["capped_cells"]) > 0]
        self.assertEqual(len(rows), 2404)
        strict_rows = [r for r in rows if r["strict_feasible"] == "1"]
        self.assertEqual(len(strict_rows), 1660)

        strict_counts = Counter()
        combined_counts = Counter()
        strict_examples = {b: [] for b in BINS}

        for r in strict_rows:
            k = int(r["capped_cells"]); u = int(r["cap_ticket_upper"])
            lo = int(r["feasible_residual_min"]); hi = int(r["feasible_residual_max"])
            n = count_interval(lo, hi, k, u)
            b = bucket(n); strict_counts[b] += 1
            if len(strict_examples[b]) < 4:
                strict_examples[b].append((r["race_id"], n, int(r["sales_won"]), k, u, lo, hi))

        for r in rows:
            k = int(r["capped_cells"]); u = int(r["cap_ticket_upper"])
            if r["strict_feasible"] == "1":
                lo = int(r["feasible_residual_min"]); hi = int(r["feasible_residual_max"])
            else:
                lo = int(r["relaxed_residual_min"]); hi = int(r["relaxed_residual_max"])
            combined_counts[bucket(count_interval(lo, hi, k, u))] += 1

        print("FINER_SORTED_PARTITION_2017_SUMMARY")
        print("strict_counts=" + ",".join(f"{b}:{strict_counts[b]}" for b in BINS))
        print("combined_counts=" + ",".join(f"{b}:{combined_counts[b]}" for b in BINS))
        for b in BINS:
            print(f"EXAMPLES {b}")
            for race_id,n,sales,k,u,lo,hi in strict_examples[b]:
                ntext = f">{LIMIT}" if n > LIMIT else str(n)
                print(f"  race={race_id} candidates={ntext} sales={sales} k={k} U={u} R={lo}-{hi}")

        self.assertEqual(sum(strict_counts.values()), 1660)
        self.assertEqual(sum(combined_counts.values()), 2404)
        self.fail("intentional temporary diagnostic stop after result output")


if __name__ == "__main__":
    unittest.main(verbosity=2)
