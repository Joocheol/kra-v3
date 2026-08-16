#!/usr/bin/env python3
"""Stage-4 Gabaix/Zipf diagnostic: race-level rank-size heterogeneity.

Two questions are separated carefully:
1. On entirely uncapped races, do normalized rank-size curves form a stable
   template that predicts held-out 2025 tail quantiles?
2. Are capped and uncapped races transferable?  We report both (a) threshold
   slopes including capped cells, which exactly diagnose whole-race selection,
   and (b) slopes computed after *removing every 9999.9 cell*, which test
   whether the still-visible 3000--7000 tail already differs below the cap.
"""
from __future__ import annotations

import math
import pathlib
import statistics

import numpy as np

from analyze_cross_market import _won, load_feasible
from analyze_masked_reconstruction import load_grids, load_races

DATA = pathlib.Path("데이터")
THRESHOLDS = (3000.0, 5000.0, 7000.0)
ANCHORS = (0.50, 0.90)
TARGET_Q = (0.95, 0.975, 0.99)
CAP_DISPLAY = 9999.9


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


def slope_triplet(odds: np.ndarray) -> tuple[float | None, float | None, float | None]:
    counts = {u: int(np.sum(odds >= u)) for u in THRESHOLDS}
    z35 = local_slope(counts[3000.0], counts[5000.0], 3000.0, 5000.0)
    z57 = local_slope(counts[5000.0], counts[7000.0], 5000.0, 7000.0)
    curvature = None if z35 is None or z57 is None else z57 - z35
    return z35, z57, curvature


def main() -> int:
    races = load_races(DATA / "races.jsonl.gz")
    feasible = load_feasible(DATA / "trifecta_feasible_sets.csv.gz")
    grids = load_grids(DATA, races, set(feasible))
    rows = []

    for idx, race_id in enumerate(sorted(feasible), 1):
        race = races[race_id]
        odds = np.asarray([float(value) for _, value in grids[race_id]], dtype=float)
        visible = odds[odds != CAP_DISPLAY]
        z35, z57, curvature = slope_triplet(odds)
        vz35, vz57, vcurvature = slope_triplet(visible)
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
            "K": len(odds),
            "field": field,
            "field_band": field_band(field),
            "turnover": turnover,
            "z35": z35,
            "z57": z57,
            "curvature": curvature,
            "visible_z35": vz35,
            "visible_z57": vz57,
            "visible_curvature": vcurvature,
            "q50": quant[0.50],
            "q90": quant[0.90],
            **{f"nq{q}": normq[q] for q in TARGET_Q},
            **{f"q{q}": quant[q] for q in TARGET_Q},
        })
        if idx % 1000 == 0:
            print(f"# summarized {idx}/{len(feasible)}", flush=True)

    # Part A: normalized template among entirely uncapped races.
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
        abslog, rel = [], []
        for r in test:
            scale = float(r["q90"]) - float(r["q50"])
            pred_log = float(r["q50"]) + template[q] * scale
            truth_log = float(r[f"q{q}"])
            abslog.append(abs(pred_log - truth_log))
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

    # Part B1: exact whole-tail selection diagnostic including capped cells.
    print("\n# local threshold slopes including capped cells")
    print("group,races,z35,z57,curvature")
    for capped in (False, True):
        group = [r for r in rows if r["capped"] == capped]
        name = "capped" if capped else "uncapped"
        z35s = [float(r["z35"]) for r in group if r["z35"] is not None]
        z57s = [float(r["z57"]) for r in group if r["z57"] is not None]
        curv = [float(r["curvature"]) for r in group if r["curvature"] is not None]
        print(f"{name},{len(group)},{describe(z35s)},{describe(z57s)},{describe(curv)}")

    # Part B2: stronger non-tautological diagnostic using only visible <cap cells.
    print("\n# visible-only local threshold slopes after removing every 9999.9 cell")
    print("group,races,z35,z57,curvature")
    for capped in (False, True):
        group = [r for r in rows if r["capped"] == capped]
        name = "capped" if capped else "uncapped"
        z35s = [float(r["visible_z35"]) for r in group if r["visible_z35"] is not None]
        z57s = [float(r["visible_z57"]) for r in group if r["visible_z57"] is not None]
        curv = [float(r["visible_curvature"]) for r in group if r["visible_curvature"] is not None]
        print(f"{name},{len(group)},{describe(z35s)},{describe(z57s)},{describe(curv)}")

    # Within-uncapped heterogeneity by field size and turnover.
    uncapped = [r for r in rows if not r["capped"]]
    turnovers = np.asarray([float(r["turnover"]) for r in uncapped])
    t1, t2 = np.quantile(turnovers, [1/3, 2/3])
    for r in uncapped:
        t = float(r["turnover"])
        r["turnover_band"] = "low" if t <= t1 else ("mid" if t <= t2 else "high")

    print("\n# uncapped visible local curvature by field-size and turnover strata")
    print("dimension,group,races,curvature")
    for dim in ("field_band", "turnover_band"):
        groups = sorted({str(r[dim]) for r in uncapped})
        for g in groups:
            sub = [r for r in uncapped if r[dim] == g]
            curv = [float(r["visible_curvature"]) for r in sub if r["visible_curvature"] is not None]
            print(f"{dim},{g},{len(sub)},{describe(curv)}")

    q99_med, q99_p90 = template_errors[0.99]
    template_ok = q99_med <= 0.15 and q99_p90 <= 0.35
    unc_all = [float(r["curvature"]) for r in rows if not r["capped"] and r["curvature"] is not None]
    cap_all = [float(r["curvature"]) for r in rows if r["capped"] and r["curvature"] is not None]
    inclusive_gap = abs(statistics.median(cap_all) - statistics.median(unc_all))
    unc_vis = [float(r["visible_curvature"]) for r in rows if not r["capped"] and r["visible_curvature"] is not None]
    cap_vis = [float(r["visible_curvature"]) for r in rows if r["capped"] and r["visible_curvature"] is not None]
    visible_gap = abs(statistics.median(cap_vis) - statistics.median(unc_vis))
    transfer_ok = visible_gap <= 0.5
    print(
        "\nSUMMARY "
        f"q99_median_relative_error={q99_med:.6f} q99_p90_relative_error={q99_p90:.6f} "
        f"inclusive_curvature_gap={inclusive_gap:.6f} visible_only_curvature_gap={visible_gap:.6f}"
    )
    print("WITHIN_UNCAPPED_TEMPLATE", "CANDIDATE" if template_ok else "REJECT")
    print("UNCAPPED_TO_CAPPED_VISIBLE_TRANSFER", "NOT_REJECTED" if transfer_ok else "REJECT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
