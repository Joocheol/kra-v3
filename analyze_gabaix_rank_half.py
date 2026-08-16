#!/usr/bin/env python3
"""Evaluate Gabaix-Ibragimov Rank-1/2 on uncapped trifecta tails.

This is deliberately a *diagnostic*, not yet a reconstruction model.  The
sample uses 2022--2025 races with no real 9999.9 cells so that every tail
observation below the display cap is known.  We estimate Pareto tail slopes at
3000/5000/7000 and test whether slopes learned on 2022--2024 predict higher
2025 exceedance counts.  Because selecting entirely uncapped races truncates
the sample below 9999.9, passing this diagnostic is necessary but not
sufficient for extrapolating beyond the real cap.
"""
from __future__ import annotations

import math
import pathlib
from collections import defaultdict

import numpy as np

from analyze_masked_reconstruction import load_grids, load_races, primary_race_ids

DATA = pathlib.Path("데이터")
THRESHOLDS = (3000.0, 5000.0, 7000.0)
TARGETS = {
    3000.0: (5000.0, 7000.0, 9000.0),
    5000.0: (7000.0, 9000.0),
    7000.0: (9000.0,),
}


def fit_rank_half(values: np.ndarray, threshold: float) -> dict[str, float | int]:
    tail = np.asarray(values[values >= threshold], dtype=float)
    tail = np.sort(tail)[::-1]
    n = len(tail)
    if n < 20:
        raise ValueError(f"too few tail observations above {threshold}: {n}")
    x = np.log(tail / threshold)
    y = np.log(np.arange(1, n + 1, dtype=float) - 0.5)
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    fitted = X @ beta
    ssr = float(np.square(y - fitted).sum())
    sst = float(np.square(y - y.mean()).sum())
    zeta = -float(beta[1])
    return {
        "n": n,
        "zeta": zeta,
        "gi_se": zeta * math.sqrt(2.0 / n),
        "r2": 1.0 - ssr / sst,
        "max": float(tail[0]),
    }


def flatten_by_year(
    grids: dict[str, list[tuple[tuple[int, int, int], object]]],
    races: dict[str, dict],
) -> dict[str, np.ndarray]:
    out: dict[str, list[float]] = defaultdict(list)
    for race_id, values in grids.items():
        year = races[race_id]["date"][:4]
        for _, value in values:
            odds = float(value)
            if odds >= 9999.9:
                raise AssertionError(f"uncapped primary race contains cap: {race_id}")
            out[year].append(odds)
    return {year: np.asarray(vals, dtype=float) for year, vals in out.items()}


def load_uncapped_odds(data: pathlib.Path) -> list[tuple[int, float]]:
    """Reusable cell-level odds sample from races with no real 9999.9 cell."""
    races = load_races(data / "races.jsonl.gz")
    wanted = primary_race_ids(data / "trifecta_feasible_sets.csv.gz")
    grids = load_grids(data, races, wanted)
    by_year = flatten_by_year(grids, races)
    return [
        (int(year), float(value))
        for year in sorted(by_year)
        for value in by_year[year]
    ]


def predict_exceedance(test_values: np.ndarray, u: float, v: float, zeta: float) -> tuple[int, float, float]:
    n_u = int(np.sum(test_values >= u))
    actual = int(np.sum(test_values >= v))
    predicted = n_u * (v / u) ** (-zeta)
    ratio = actual / predicted if predicted > 0 else math.nan
    return actual, predicted, ratio


def main() -> int:
    races = load_races(DATA / "races.jsonl.gz")
    wanted = primary_race_ids(DATA / "trifecta_feasible_sets.csv.gz")
    grids = load_grids(DATA, races, wanted)
    by_year = flatten_by_year(grids, races)

    train = np.concatenate([by_year[y] for y in ("2022", "2023", "2024")])
    test = by_year["2025"]
    pooled = np.concatenate([by_year[y] for y in sorted(by_year)])

    print("# Gabaix-Ibragimov Rank-1/2 diagnostic")
    print("# sample: 2022-2025 races with no real 9999.9 cells")
    print("# caveat: this sample is selected on maximum odds < 9999.9, so it is right-truncated and cannot by itself justify extrapolation beyond the cap")
    print("sample,threshold,n,zeta,GI_se,R2,max_odds")
    for sample_name, values in [("train_2022_2024", train), ("test_2025", test), ("pooled_2022_2025", pooled)]:
        for threshold in THRESHOLDS:
            fit = fit_rank_half(values, threshold)
            print(
                f"{sample_name},{threshold:.0f},{fit['n']},{fit['zeta']:.6f},"
                f"{fit['gi_se']:.6f},{fit['r2']:.6f},{fit['max']:.1f}"
            )

    print("\n# year-specific threshold stability")
    print("year,threshold,n,zeta,GI_se,R2")
    for year in sorted(by_year):
        for threshold in THRESHOLDS:
            fit = fit_rank_half(by_year[year], threshold)
            print(
                f"{year},{threshold:.0f},{fit['n']},{fit['zeta']:.6f},"
                f"{fit['gi_se']:.6f},{fit['r2']:.6f}"
            )

    print("\n# 2025 out-of-sample higher-threshold exceedance prediction")
    print("fit_u,target_v,zeta_train,test_n_ge_u,actual_n_ge_v,predicted_n_ge_v,actual_over_predicted")
    for u in THRESHOLDS:
        fit = fit_rank_half(train, u)
        zeta = float(fit["zeta"])
        n_u = int(np.sum(test >= u))
        for v in TARGETS[u]:
            actual, predicted, ratio = predict_exceedance(test, u, v, zeta)
            print(
                f"{u:.0f},{v:.0f},{zeta:.6f},{n_u},{actual},{predicted:.3f},{ratio:.6f}"
            )

    # A compact verdict helper.  This is intentionally conservative: threshold
    # instability over 20% or OOS count errors over 25% is enough to reject a
    # simple single-exponent Pareto tail as a reconstruction prior.
    train_fits = [fit_rank_half(train, u) for u in THRESHOLDS]
    zetas = np.asarray([float(f["zeta"]) for f in train_fits])
    rel_span = float((zetas.max() - zetas.min()) / zetas.mean())
    errors = []
    for u in THRESHOLDS:
        zeta = float(fit_rank_half(train, u)["zeta"])
        for v in TARGETS[u]:
            _, _, ratio = predict_exceedance(test, u, v, zeta)
            errors.append(abs(ratio - 1.0))
    max_oos_error = max(errors)
    status = "PASS_CANDIDATE" if rel_span <= 0.20 and max_oos_error <= 0.25 else "REJECT_SIMPLE_PARETO"
    print(
        f"\nVERDICT {status} train_zeta_relative_span={rel_span:.6f} "
        f"max_2025_exceedance_relative_error={max_oos_error:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
