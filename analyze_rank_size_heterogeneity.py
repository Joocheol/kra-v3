#!/usr/bin/env python3
"""Stage-4 Gabaix/Zipf diagnostic: race-level rank-size heterogeneity.

This evaluates the user's original idea at the race level rather than pooling
all odds cells.  Two complementary questions are asked:

1. On entirely uncapped races, do normalized rank-size/quantile curves collapse
   to a stable common template that predicts held-out 2025 tail quantiles?
2. Using threshold exceedance counts that are exactly observable even for
   capped races (a 9999.9 cell is certainly above 3000/5000/7000), do capped
   and uncapped races already have different *pre-cap* local tail slopes?

If the second answer is yes, learning one global tail law only from uncapped
races is selection-biased even if the within-uncapped template looks stable.
"""
from __future__ import annotations

import math
import pathlib
import statistics
from collections import defaultdict

import numpy as np

from analyze_cross_market import _won, load_feasible, load_race_records
from check_coherence import load_month

DATA = pathlib.Path("데이터")
THRESHOLDS = (3000.0, 5000.0, 7000.0)
ANCHORS = (0.50, 0.90)
TARGET_Q = (0.95, 0.975, 0.99)


def local_slope(n_lo: int, n_hi: int, lo: float, hi: float) -> float | None:
    if n_lo <= 0 or n_hi <= 0 or n_hi > n_lo:
        return None
    return -math.log(n_hi / n_lo) / math.log(hi / lo)


def field_band(n: int) -> str:
    if n <= 9:
        return "<=9"
    if n <= 11:
        return "10-11"
    return ">=12"


def describe(values: list[float]) -> str:
    if not values:
        return "n=0"
    a = np.asarray(values, dtype=float)
    q25, med, q75 = np.quantile(a, [0.25, 0.5, 0.75])
    return f"n={len(a)};median={med:.6f};q25={q25:.6f};q75={q75:.6f}"


def main() -> int:
    races = load_race_records(DATA / "races.jsonl.gz")
    feasible = load_feasible(DATA / "trifecta_feasible_sets.csv.gz")
    months: dict[str, dict] = {}
    rows = []

    for idx, race_id in enumerate(sorted(feasible), 1):
        race = races[race_id]
        month = race["date"][:7]
        if month not in months:
            months[month] = load_month(DATA, month)
        market = months[month].get(race_id)
        if market is None or not market["trifecta"]:
            raise ValueError(f"{race_id}: missing trifecta market")
        odds = np.asarray(list(market["trifecta"].values()), dtype=float)
        K = len(odds)
        counts = {u: int(np.sum(odds >= u)) for u in THRESHOLDS}
        z35 = local_slope(counts[3000.0], counts[5000.0], 3000.0, 5000.0)
        z57 = local_slope(counts[5000.0], counts[7000.0], 5000.0, 7000.0)
        capped_cells = int(feasible[race_id]["capped_cells"])
        field = len(set(race["horses"]) - set(race.get("scratched") or []))
        turnover = _won(race["sales"]["삼쌍승식"])
        logs = np.log(odds)
        quant = {q: float(np.quantile(logs, q)) for q in (*ANCHORS, *TARGET_Q)}
        scale = quant[0.90] - quant[0.50]
        normq = {
            q: (quant[q] - quant[0.50]) / scale if scale > 0 else math.nan
            for q in TARGET_Q
        }
        rows.append({
            "race_id": race_id,
            "date": race["date"],
            "year": int(race["date"][:4]),
            "capped": capped_cells > 0,
            "capped_cells": capped_cells,
            "K": K,
            "field": field,
            "field_band": field_band(field),
            "turnover": turnover,
            "z35": z35,
            "z57": z57,
            "curvature": None if z35 is None or z57 is None else z57 - z35,
            "q50": quant[0.50],
            "q90": quant[0.90],
            **{f"nq{q}": normq[q] for q in TARGET_Q},
            **{f"q{q}": quant[q] for q in TARGET_Q},
        })
        if idx % 1000 == 0:
            print(f"# scanned {idx}/{len(feasible)}", flush=True)

    # ---- Part A: normalized quantile template on uncapped races ----------
    train = [r for r in rows if not r["capped"] and r["year"] <= 2024]
    test = [r for r in rows if not r["capped"] and r["year"] == 2025]
    template = {
        q: statistics.median(float(r[f"nq{q}"]) for r in train if math.isfinite(float(r[f"nq{q}"])))
        for q in TARGET_Q
    }
    print("# normalized rank-size quantile collapse: anchors are log-odds q50 and q90")
    print("target_q,train_n,template_normalized,test_n,median_abs_log_error,p90_abs_log_error,median_relative_odds_error,p90_relative_odds_error")
    template_errors = {}
    for q in TARGET_Q:
        abslog = []
        rel = []
        for r in test:
            scale = float(r["q90"]) - float(r["q50"])
            pred_log = float(r["q50"]) + template[q] * scale
            truth_log = float(r[f"q{q}"])
            e = abs(pred_log - truth_log)
            abslog.append(e)
            rel.append(abs(math.exp(pred_log - truth_log) - 1.0))
        a = np.asarray(abslog)
        rr = np.asarray(rel)
        template_errors[q] = (float(np.median(rr)), float(np.quantile(rr, 0.90)))
        print(
            f"{q:.3f},{len(train)},{template[q]:.6f},{len(test)},"
            f"{np.median(a):.6f},{np.quantile(a,0.90):.6f},"
            f"{np.median(rr):.6f},{np.quantile(rr,0.90):.6f}"
        )

    print("\n# training normalized-quantile dispersion")
    print("target_q,n,q25,median,q75,iqr")
    for q in TARGET_Q:
        vals = np.asarray([float(r[f"nq{q}"]) for r in train])
        q25, med, q75 = np.quantile(vals, [0.25, 0.5, 0.75])
        print(f"{q:.3f},{len(vals)},{q25:.6f},{med:.6f},{q75:.6f},{q75-q25:.6f}")

    # ---- Part B: tail slopes identifiable in both capped and uncapped -----
    print("\n# local threshold slopes by capped status")
    print("group,races,z35,z57,curvature")
    for capped in (False, True):
        group = [r for r in rows if r["capped"] == capped]
        name = "capped" if capped else "uncapped"
        z35 = [float(r["z35"]) for r in group if r["z35"] is not None]
        z57 = [float(r["z57"]) for r in group if r["z57"] is not None]
        curv = [float(r["curvature"]) for r in group if r["curvature"] is not None]
        print(f"{name},{len(group)},{describe(z35)},{describe(z57)},{describe(curv)}")

    # Strata among uncapped races: if common shape exists, these should not
    # move dramatically merely with field size or turnover.
    uncapped = [r for r in rows if not r["capped"]]
    turnovers = np.asarray([float(r["turnover"]) for r in uncapped])
    t1, t2 = np.quantile(turnovers, [1/3, 2/3])
    for r in uncapped:
        t = float(r["turnover"])
        r["turnover_band"] = "low" if t <= t1 else ("mid" if t <= t2 else "high")

    print("\n# uncapped local curvature by field-size and turnover strata")
    print("dimension,group,races,curvature")
    for dim in ("field_band", "turnover_band"):
        groups = sorted({str(r[dim]) for r in uncapped})
        for g in groups:
            sub = [r for r in uncapped if r[dim] == g]
            curv = [float(r["curvature"]) for r in sub if r["curvature"] is not None]
            print(f"{dim},{g},{len(sub)},{describe(curv)}")

    # Compact diagnostic verdict.  The common normalized template is retained
    # only if held-out q99 median error <=15% and p90 <=35%.  Global transfer
    # from uncapped to capped races is rejected if median local curvature differs
    # by more than 0.5 between capped and uncapped groups.
    q99_med, q99_p90 = template_errors[0.99]
    template_ok = q99_med <= 0.15 and q99_p90 <= 0.35
    unc_curv = [float(r["curvature"]) for r in rows if not r["capped"] and r["curvature"] is not None]
    cap_curv = [float(r["curvature"]) for r in rows if r["capped"] and r["curvature"] is not None]
    curv_gap = abs(statistics.median(cap_curv) - statistics.median(unc_curv))
    transfer_ok = curv_gap <= 0.5
    print(
        "\nSUMMARY "
        f"q99_median_relative_error={q99_med:.6f} q99_p90_relative_error={q99_p90:.6f} "
        f"capped_uncapped_median_curvature_gap={curv_gap:.6f}"
    )
    print("WITHIN_UNCAPPED_TEMPLATE", "CANDIDATE" if template_ok else "REJECT")
    print("UNCAPPED_TO_CAPPED_TRANSFER", "NOT_REJECTED" if transfer_ok else "REJECT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
