#!/usr/bin/env python3
"""Allocation-free trifecta calibration/FLB curve over odds bands.

Uncapped cells are completed inside their exact one-decimal accounting
intervals.  All displayed-9999.9 cells remain one aggregate terminal band, so
no cross-pool or within-cap allocation can manufacture the tail result.
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

SCENARIO = "residual_mid"
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


def race_band_mass(race: dict, market: dict, info: dict[str, int]) -> tuple[np.ndarray, int]:
    odds = market["trifecta"]
    sales_digits = "".join(c for c in str(race["sales"]["삼쌍승식"]) if c.isdigit())
    sales = int(sales_digits)
    total = sales // 100
    residual = int(info[SCENARIO])
    uncapped = [(combo, float(value)) for combo, value in odds.items() if float(value) != 9999.9]
    lower, upper, target = [], [], []
    for _, value in uncapped:
        candidates = displayed_ticket_interval(sales, Decimal(str(value)))
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


def summarize(name: str, records: list[tuple[str, np.ndarray, int]], seed: int) -> None:
    ranks = np.arange(len(LABELS), dtype=float)
    by_date_o: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(len(LABELS)))
    by_date_e: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(len(LABELS)))
    by_date_disp: dict[str, float] = defaultdict(float)
    by_date_n: dict[str, int] = defaultdict(int)
    for date, mass, winner_band in records:
        by_date_o[date][winner_band] += 1.0
        by_date_e[date] += mass
        by_date_disp[date] += float(winner_band - mass @ ranks)
        by_date_n[date] += 1

    dates = sorted(by_date_o)
    cluster_o = np.vstack([by_date_o[d] for d in dates])
    cluster_e = np.vstack([by_date_e[d] for d in dates])
    cluster_disp = np.asarray([by_date_disp[d] for d in dates], dtype=float)
    cluster_n = np.asarray([by_date_n[d] for d in dates], dtype=float)
    O = cluster_o.sum(axis=0)
    E = cluster_e.sum(axis=0)
    ratio = O / E

    rng = np.random.default_rng(seed)
    g = len(dates)
    weights = rng.multinomial(g, np.full(g, 1.0 / g), size=BOOTSTRAP_DRAWS)
    ratio_b = (weights @ cluster_o) / (weights @ cluster_e)
    ratio_lo = np.quantile(ratio_b, 0.025, axis=0)
    ratio_hi = np.quantile(ratio_b, 0.975, axis=0)

    # Nearby high-odds comparison: 3000--9999.8 vs terminal capped set.
    near_o = cluster_o[:, 6:9].sum(axis=1)
    near_e = cluster_e[:, 6:9].sum(axis=1)
    near_ratio = near_o.sum() / near_e.sum()
    cap_ratio = O[-1] / E[-1]
    near_b = (weights @ near_o) / (weights @ near_e)
    cap_b = (weights @ cluster_o[:, -1]) / (weights @ cluster_e[:, -1])
    contrast = cap_ratio - near_ratio
    contrast_b = cap_b - near_b
    c_lo, c_hi = np.quantile(contrast_b, [0.025, 0.975])
    p_cap_not_lower = (1.0 + float(np.sum(contrast_b >= 0.0))) / (BOOTSTRAP_DRAWS + 1.0)

    disp_b = (weights @ cluster_disp) / (weights @ cluster_n)
    disp = float(cluster_disp.sum() / cluster_n.sum())
    d_lo, d_hi = np.quantile(disp_b, [0.025, 0.975])

    for i, label in enumerate(LABELS):
        print(
            f"BAND,{name},{label},{int(O[i])},{E[i]:.6f},{ratio[i]:.6f},"
            f"{ratio_lo[i]:.6f},{ratio_hi[i]:.6f}"
        )
    print(
        f"CONTRAST,{name},3000--9999.8_vs_cap,near={near_ratio:.6f},cap={cap_ratio:.6f},"
        f"cap_minus_near={contrast:.6f},CI=[{c_lo:.6f},{c_hi:.6f}],"
        f"bootstrap_fraction_cap_not_lower={p_cap_not_lower:.6f}"
    )
    print(
        f"ORDINAL,{name},races={int(cluster_n.sum())},dates={len(dates)},"
        f"winner_minus_bet_rank={disp:.6f},CI=[{d_lo:.6f},{d_hi:.6f}]"
    )


def main() -> int:
    data = pathlib.Path("데이터")
    races = load_race_records(data / "races.jsonl.gz")
    feasible = load_feasible(data / "trifecta_feasible_sets.csv.gz")
    by_month = {}
    records: list[tuple[str, np.ndarray, int]] = []

    for idx, race_id in enumerate(sorted(feasible), 1):
        race = races[race_id]
        month = race["date"][:7]
        if month not in by_month:
            by_month[month] = load_month(data, month)
        market = by_month[month].get(race_id)
        if market is None:
            raise ValueError(f"{race_id}: missing market")
        mass, winner_band = race_band_mass(race, market, feasible[race_id])
        records.append((race["date"], mass, winner_band))
        if idx % 1000 == 0:
            print(f"# scanned {idx}/{len(feasible)}", flush=True)

    print("# O/E < 1 means the odds band receives more ticket mass than its realised winner frequency.")
    summarize("2022--2025", records, SEED)
    for offset, year in enumerate(("2022", "2023", "2024", "2025"), 1):
        summarize(year, [r for r in records if r[0][:4] == year], SEED + offset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
