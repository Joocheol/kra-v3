#!/usr/bin/env python3
"""Test whether pre-2022 rounding mismatches admit a nearby earlier pool snapshot.

For every race containing an uncapped trifecta cell that is incompatible with
the recorded final pool total, this diagnostic asks whether there is a *single*
earier total ticket count T' in [window*T, T] that makes every uncapped cell
compatible with the maintained 73%, 100-won, positive-half-up display model.

The search is exact inside the declared window.  Candidate totals are generated
from the incompatible cells first; those cells have narrow integer-ticket
intervals by construction.  Candidate totals are then tested from closest to
the final pool downward, stopping at the first total that preserves every
uncapped cell.  Capped 9999.9 cells and the unresolved 1.0 lower-code cells are
not used to select T'.

The expensive search is run once at the widest reported window (5%).  Because
we recover the *closest* valid earlier total, the 1% result is exactly the
subset whose recovered gap is at most 1%; no second data scan is necessary.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import pathlib
from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from statistics import median

from analyze_feasible_sets import NUMERIC_ODDS, PAGE_KEY, POOL_LABEL, _won
from kra.feasible import TAKE_FRACTION, displayed_ticket_interval, displayed_total_interval


def load_races(path: pathlib.Path) -> dict[str, dict]:
    races: dict[str, dict] = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            race = json.loads(line)
            races[race["race_id"]] = race
    return races


def load_uncapped_cells(data_dir: pathlib.Path, races: dict[str, dict]) -> dict[str, list[Decimal]]:
    values: dict[str, list[Decimal]] = defaultdict(list)
    partitions = sorted((data_dir / "cells" / f"page_key={PAGE_KEY}").glob("*.csv.gz"))
    if not partitions:
        raise FileNotFoundError(f"no {PAGE_KEY} partitions")
    for path in partitions:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["race_id"] not in races:
                    continue
                raw = row["cell_raw"]
                if (
                    row["section"] != "body"
                    or row["spanned"] != "0"
                    or not NUMERIC_ODDS.fullmatch(raw)
                    or raw in {"9999.9", "1.0"}
                ):
                    continue
                values[row["race_id"]].append(Decimal(raw))
    return values


def _ceil_fraction(x: Fraction) -> int:
    return -(-x.numerator // x.denominator)


def candidate_totals_for_cell(value: Decimal, lo: int, hi: int) -> set[int]:
    """All T in [lo, hi] for which some positive integer n displays value."""
    d10 = int(value * 10)
    # 10*O = 10*p*T/(q*n), and half-up owns [d-0.5,d+0.5).
    p, q = TAKE_FRACTION.numerator, TAKE_FRACTION.denominator
    n_lo = Fraction(20 * p * lo, q * (2 * d10 + 1))
    n_hi = Fraction(20 * p * hi, q * (2 * d10 - 1))
    first_n = max(1, _ceil_fraction(n_lo))
    last_n = n_hi.numerator // n_hi.denominator
    out: set[int] = set()
    for n in range(first_n, last_n + 1):
        totals = displayed_total_interval(n, value)
        start = max(lo, totals.start)
        stop = min(hi + 1, totals.stop)
        if start < stop:
            out.update(range(start, stop))
    return out


def explain_race(values: list[Decimal], final_t: int, window_bp: int) -> tuple[int | None, int, int]:
    lo = max(1, (final_t * (10_000 - window_bp) + 9_999) // 10_000)
    incompatible = [
        value for value in values
        if not displayed_ticket_interval(final_t * 100, value)
    ]
    if not incompatible:
        return final_t, 0, 1

    candidates: set[int] | None = None
    for value in sorted(incompatible, reverse=True):
        cell = candidate_totals_for_cell(value, lo, final_t - 1)
        candidates = cell if candidates is None else candidates & cell
        if not candidates:
            return None, len(incompatible), 0

    assert candidates is not None
    n_candidates = len(candidates)
    for total in sorted(candidates, reverse=True):
        if all(displayed_ticket_interval(total * 100, value) for value in values):
            return total, len(incompatible), n_candidates
    return None, len(incompatible), n_candidates


def search(data_dir: pathlib.Path, max_window_bp: int = 500) -> dict:
    races = load_races(data_dir / "races.jsonl.gz")
    cells = load_uncapped_cells(data_dir, races)
    failing_by_year: dict[str, int] = defaultdict(int)
    explained = []
    failing_races = 0

    for race_id in sorted(races):
        values = cells.get(race_id, [])
        if not values:
            continue
        sales = _won(races[race_id]["sales"][POOL_LABEL])
        if sales % 100:
            continue
        final_t = sales // 100
        incompatible = sum(
            not displayed_ticket_interval(sales, value) for value in values
        )
        if not incompatible:
            continue
        failing_races += 1
        year = races[race_id]["date"][:4]
        failing_by_year[year] += 1
        best, bad, n_candidates = explain_race(values, final_t, max_window_bp)
        if best is not None and best != final_t:
            gap_bp = (final_t - best) * 10_000 / final_t
            explained.append((race_id, year, best, final_t, gap_bp, bad, n_candidates))

    return {
        "max_window_bp": max_window_bp,
        "failing_races": failing_races,
        "failing_by_year": dict(sorted(failing_by_year.items())),
        "explained": explained,
    }


def summarize(raw: dict, window_bp: int) -> dict:
    selected = [row for row in raw["explained"] if row[4] <= window_bp + 1e-12]
    explained_by_year: dict[str, int] = defaultdict(int)
    for row in selected:
        explained_by_year[row[1]] += 1
    by_year = {
        year: [count, explained_by_year.get(year, 0)]
        for year, count in raw["failing_by_year"].items()
    }
    return {
        "window_bp": window_bp,
        "failing_races": raw["failing_races"],
        "explained_races": len(selected),
        "by_year": by_year,
        "median_gap_bp": median([row[4] for row in selected]) if selected else None,
        "max_gap_bp": max([row[4] for row in selected]) if selected else None,
        "examples": [
            (row[0], row[2], row[3], row[4], row[5], row[6])
            for row in sorted(selected, key=lambda row: row[4])[:10]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=pathlib.Path, default=pathlib.Path("데이터"))
    args = parser.parse_args()
    raw = search(args.data_dir, max_window_bp=500)
    for window_bp in (100, 500):
        result = summarize(raw, window_bp)
        print("SNAPSHOT_DIAGNOSTIC " + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
