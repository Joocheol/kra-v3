#!/usr/bin/env python3
"""Date-clustered FLB diagnostic for the capped trifecta tail.

The estimand is deliberately allocation-free. For each race, Y is one when
the realised trifecta lies in the displayed-9999.9 set and Q is the aggregate
ticket mass assigned to that set by the frozen accounting feasible-set
scenario. FLB direction is Y < Q: the extreme-longshot set receives more
betting mass than its realised frequency.
"""
from __future__ import annotations

import csv
import gzip
import math
import pathlib
from collections import defaultdict

import numpy as np

DATA = pathlib.Path("데이터")
SCENARIOS = ("residual_min", "residual_mid", "residual_max")
BOOTSTRAP_DRAWS = 20000
SEED = 20260816


def load_feasible(path: pathlib.Path) -> dict[str, dict[str, float]]:
    out = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not ("2022" <= row["year"] <= "2025" and row["strict_feasible"] == "1"):
                continue
            total = int(row["total_tickets"])
            lo = int(row["feasible_residual_min"])
            hi = int(row["feasible_residual_max"])
            counts = {
                "residual_min": lo,
                "residual_mid": (lo + hi) // 2,
                "residual_max": hi,
            }
            out[row["race_id"]] = {
                scenario: counts[scenario] / total for scenario in SCENARIOS
            }
    return out


def load_outcomes(path: pathlib.Path) -> list[dict[str, object]]:
    rows = []
    seen = set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["model"] != "trifecta_uniform_fractional":
                continue
            race_id = row["race_id"]
            if race_id in seen:
                raise ValueError(f"duplicate primary outcome row: {race_id}")
            seen.add(race_id)
            rows.append({
                "race_id": race_id,
                "date": row["date"],
                "year": row["year"],
                "y": int(row["outcome_capped"]),
            })
    return rows


def clustered_result(
    rows: list[dict[str, object]],
    feasible: dict[str, dict[str, float]],
    scenario: str,
    seed: int,
) -> dict[str, float | int]:
    merged = []
    for row in rows:
        info = feasible.get(str(row["race_id"]))
        if info is None:
            continue
        merged.append((str(row["date"]), float(row["y"]), float(info[scenario])))
    if not merged:
        raise ValueError("empty merged sample")

    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for date, y, q in merged:
        by_date[date].append((y, q))
    dates = sorted(by_date)
    O = sum(y for _, y, _ in merged)
    E = sum(q for _, _, q in merged)
    n = len(merged)
    mu = (O - E) / n

    cluster_o = np.asarray([sum(y for y, _ in by_date[d]) for d in dates], dtype=float)
    cluster_e = np.asarray([sum(q for _, q in by_date[d]) for d in dates], dtype=float)
    cluster_n = np.asarray([len(by_date[d]) for d in dates], dtype=float)
    influences = (cluster_o - cluster_e) - mu * cluster_n
    G = len(dates)
    se = math.sqrt((G / (G - 1)) * float(np.dot(influences, influences))) / n if G > 1 else math.nan
    z = mu / se if se > 0 else math.nan
    p_one = 0.5 * math.erfc(-z / math.sqrt(2)) if math.isfinite(z) else math.nan

    rng = np.random.default_rng(seed)
    weights = rng.multinomial(G, np.full(G, 1.0 / G), size=BOOTSTRAP_DRAWS)
    obs_b = weights @ cluster_o
    exp_b = weights @ cluster_e
    n_b = weights @ cluster_n
    ratios = obs_b / exp_b
    mus = (obs_b - exp_b) / n_b
    ratio_lo, ratio_hi = np.quantile(ratios, [0.025, 0.975])
    ratio_u95 = np.quantile(ratios, 0.95)
    mu_lo, mu_hi = np.quantile(mus, [0.025, 0.975])
    mu_u95 = np.quantile(mus, 0.95)
    return {
        "races": n,
        "dates": G,
        "observed": O,
        "expected": E,
        "ratio": O / E,
        "ratio_lo": float(ratio_lo),
        "ratio_hi": float(ratio_hi),
        "ratio_u95": float(ratio_u95),
        "mean_diff": mu,
        "mean_diff_lo": float(mu_lo),
        "mean_diff_hi": float(mu_hi),
        "mean_diff_u95": float(mu_u95),
        "z": z,
        "p_one": p_one,
    }


def main() -> int:
    feasible = load_feasible(DATA / "trifecta_feasible_sets.csv.gz")
    outcomes = load_outcomes(DATA / "outcome_robustness.csv.gz")
    samples = (
        ("2025", lambda y: y == "2025"),
        ("2022--2024", lambda y: "2022" <= y <= "2024"),
        ("2022--2025", lambda y: "2022" <= y <= "2025"),
    )
    print("sample,scenario,races,dates,observed,expected,O_over_E,ratio_ci_low,ratio_ci_high,ratio_one_sided_95_upper,mean_Y_minus_Q,mean_ci_low,mean_ci_high,mean_one_sided_95_upper,cluster_z,p_one_sided")
    k = 0
    for sample, keep in samples:
        subset = [row for row in outcomes if keep(str(row["year"]))]
        for scenario in SCENARIOS:
            result = clustered_result(subset, feasible, scenario, SEED + k)
            k += 1
            print(
                f"{sample},{scenario},{result['races']},{result['dates']},"
                f"{int(result['observed'])},{result['expected']:.6f},{result['ratio']:.6f},"
                f"{result['ratio_lo']:.6f},{result['ratio_hi']:.6f},{result['ratio_u95']:.6f},"
                f"{result['mean_diff']:.8f},{result['mean_diff_lo']:.8f},{result['mean_diff_hi']:.8f},"
                f"{result['mean_diff_u95']:.8f},{result['z']:.4f},{result['p_one']:.6f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
