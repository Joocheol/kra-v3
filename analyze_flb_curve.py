#!/usr/bin/env python3
"""Allocation-free trifecta FLB curve over uncapped odds bands plus 9999.9.

For uncapped cells, accounting-consistent ticket counts are completed inside
the displayed-odds rounding intervals.  All 9999.9 cells in a race are kept as
one aggregate terminal band; no within-cap allocation is made.  Thus the
full-curve diagnostic does not mechanically inherit an FLB pattern from any
cross-pool reconstruction model.
"""
from __future__ import annotations

import math
import pathlib
from collections import defaultdict
from decimal import Decimal

import numpy as np

from analyze_cross_market import load_feasible, load_race_records
from analyze_masked_reconstruction import bounded_integer_projection
from check_coherence import load_month
from kra.feasible import displayed_ticket_interval

SCENARIOS = ("residual_min", "residual_mid", "residual_max")
# Ordered gross-payout bands; the terminal category is the displayed cap set.
EDGES = (0.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, 5000.0, 7000.0, 9999.85)
LABELS = (
    "<10", "10--30", "30--100", "100--300", "300--1000",
    "1000--3000", "3000--5000", "5000--7000", "7000--9999.8", "9999.9 cap",
)
BOOTSTRAP_DRAWS = 20000
SEED = 20260816
TAKE = 0.73


def odds_band(value: float) -> int:
    for i in range(len(EDGES) - 1):
        if EDGES[i] <= value < EDGES[i + 1]:
            return i
    raise ValueError(f"uncapped odds outside bands: {value}")


def race_band_mass(race: dict, market: dict, info: dict[str, int], scenario: str) -> tuple[np.ndarray, int]:
    odds = market["trifecta"]
    sales_digits = "".join(c for c in str(race["sales"]["삼쌍승식"]) if c.isdigit())
    total = int(sales_digits) // 100
    residual = int(info[scenario])
    uncapped = [(combo, float(value)) for combo, value in odds.items() if float(value) != 9999.9]
    lower, upper, target = [], [], []
    for _, value in uncapped:
        candidates = displayed_ticket_interval(int(sales_digits), Decimal(str(value)))
        if not candidates:
            raise ValueError(f"{race['race_id']}: no ticket interval for {value}")
        lower.append(candidates.start)
        upper.append(candidates.stop - 1)
        target.append(TAKE * total / value)
    if uncapped:
        counts = bounded_integer_projection(
            np.asarray(target, dtype=float),
            np.asarray(lower, dtype=np.int64),
            np.asarray(upper, dtype=np.int64),
            total - residual,
        )
    else:
        counts = np.asarray([], dtype=np.int64)
    mass = np.zeros(len(LABELS), dtype=float)
    for (_, value), count in zip(uncapped, counts):
        mass[odds_band(value)] += count / total
    mass[-1] = residual / total
    if not math.isclose(float(mass.sum()), 1.0, abs_tol=1e-12):
        raise AssertionError(f"{race['race_id']}: band mass does not sum to one")

    arrival = tuple((race.get("arrival") or [])[:3])
    if len(arrival) != 3 or len(set(arrival)) != 3 or arrival not in odds:
        raise ValueError(f"{race['race_id']}: invalid realised trifecta")
    winner_odds = float(odds[arrival])
    winner_band = len(LABELS) - 1 if winner_odds == 9999.9 else odds_band(winner_odds)
    return mass, winner_band


def bootstrap_cluster(
    cluster_o: np.ndarray,
    cluster_e: np.ndarray,
    cluster_score: np.ndarray,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, tuple[float, float], float]:
    g = cluster_o.shape[0]
    rng = np.random.default_rng(seed)
    weights = rng.multinomial(g, np.full(g, 1.0 / g), size=BOOTSTRAP_DRAWS)
    ob = weights @ cluster_o
    eb = weights @ cluster_e
    ratios = np.divide(ob, eb, out=np.full_like(ob, np.nan), where=eb > 0)
    score_b = (weights @ cluster_score) / (weights.sum(axis=1))
    lo = np.nanquantile(ratios, 0.025, axis=0)
    hi = np.nanquantile(ratios, 0.975, axis=0)
    score_ci = tuple(np.quantile(score_b, [0.025, 0.975]))
    score_p_one = (1.0 + float(np.sum(score_b >= 0.0))) / (BOOTSTRAP_DRAWS + 1.0)
    return lo, hi, score_ci, score_p_one


def main() -> int:
    data = pathlib.Path("데이터")
    races = load_race_records(data / "races.jsonl.gz")
    feasible = load_feasible(data / "trifecta_feasible_sets.csv.gz")
    by_month = {}

    # Cache race-level masses once per scenario; the raw market is common.
    records: dict[str, list[tuple[str, np.ndarray, int]]] = {s: [] for s in SCENARIOS}
    for idx, race_id in enumerate(sorted(feasible), 1):
        race = races[race_id]
        month = race["date"][:7]
        if month not in by_month:
            by_month[month] = load_month(data, month)
        market = by_month[month].get(race_id)
        if market is None:
            raise ValueError(f"{race_id}: missing market")
        for scenario in SCENARIOS:
            mass, winner_band = race_band_mass(race, market, feasible[race_id], scenario)
            records[scenario].append((race["date"], mass, winner_band))
        if idx % 1000 == 0:
            print(f"# scanned {idx}/{len(feasible)}", flush=True)

    ranks = np.arange(len(LABELS), dtype=float)
    print("scenario,band,observed,expected,O_over_E,ratio_ci_low,ratio_ci_high,take_adjusted_return")
    print("# global_score = winner band rank minus ticket-mass-weighted expected band rank; negative supports FLB")
    for s_idx, scenario in enumerate(SCENARIOS):
        by_date_o: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(len(LABELS)))
        by_date_e: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(len(LABELS)))
        by_date_score: dict[str, float] = defaultdict(float)
        for date, mass, winner_band in records[scenario]:
            by_date_o[date][winner_band] += 1.0
            by_date_e[date] += mass
            by_date_score[date] += float(winner_band - mass @ ranks)
        dates = sorted(by_date_o)
        cluster_o = np.vstack([by_date_o[d] for d in dates])
        cluster_e = np.vstack([by_date_e[d] for d in dates])
        cluster_score_sum = np.asarray([by_date_score[d] for d in dates], dtype=float)
        cluster_n = np.asarray([cluster_o[i].sum() for i in range(len(dates))])
        O = cluster_o.sum(axis=0)
        E = cluster_e.sum(axis=0)
        ratio = O / E

        # For the score bootstrap, resampling dates with unequal race counts
        # must divide by the resampled number of races, not number of dates.
        rng = np.random.default_rng(SEED + s_idx)
        g = len(dates)
        weights = rng.multinomial(g, np.full(g, 1.0 / g), size=BOOTSTRAP_DRAWS)
        ob = weights @ cluster_o
        eb = weights @ cluster_e
        ratio_b = ob / eb
        ratio_lo = np.quantile(ratio_b, 0.025, axis=0)
        ratio_hi = np.quantile(ratio_b, 0.975, axis=0)
        score_b = (weights @ cluster_score_sum) / (weights @ cluster_n)
        score = float(cluster_score_sum.sum() / cluster_n.sum())
        score_lo, score_hi = np.quantile(score_b, [0.025, 0.975])
        p_one = (1.0 + float(np.sum(score_b >= 0.0))) / (BOOTSTRAP_DRAWS + 1.0)

        for i, label in enumerate(LABELS):
            print(
                f"{scenario},{label},{int(O[i])},{E[i]:.6f},{ratio[i]:.6f},"
                f"{ratio_lo[i]:.6f},{ratio_hi[i]:.6f},{TAKE*ratio[i]:.6f}"
            )
        print(
            f"GLOBAL {scenario} races={int(cluster_n.sum())} dates={len(dates)} "
            f"ordinal_FLB_score={score:.6f} CI=[{score_lo:.6f},{score_hi:.6f}] "
            f"one_sided_p={p_one:.6f}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
