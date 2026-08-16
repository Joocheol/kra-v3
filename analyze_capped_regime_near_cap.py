#!/usr/bin/env python3
"""Near-cap extension of same-regime pseudo-censoring at 8000/9000 odds.

Uses the exact same design as analyze_capped_regime_masking.py but pushes the
virtual censoring threshold close to the real 9999.9 display cap.  Genuine cap
cells remain excluded from both inputs and truth.  This is the decisive check
for whether exacta/trio ranking signals survive near the actual censoring edge.
"""
from __future__ import annotations

import pathlib

from analyze_cross_market import load_feasible
from analyze_masked_reconstruction import load_cross_pool_odds, load_grids, load_races
from analyze_capped_regime_masking import (
    METHODS, build_experiment, coef_text, evaluate, fit_coefficients,
)

THRESHOLDS=(8000.0,9000.0)


def main()->int:
    data=pathlib.Path("데이터")
    races=load_races(data/"races.jsonl.gz")
    feasible=load_feasible(data/"trifecta_feasible_sets.csv.gz")
    wanted={rid for rid,info in feasible.items() if int(info["capped_cells"])>0}
    grids=load_grids(data,races,wanted)
    cross=load_cross_pool_odds(data,wanted)

    print("# Near-cap same-regime pseudo-censoring")
    print("threshold,method,train_races,test_races,train_cells,test_cells,coef,train_ce,test_ce,MAE,log1p_RMSE,exact,median_spearman,median_truth_mass_in_pred_top_third,median_pred_mass_top_third")
    for threshold in THRESHOLDS:
        exps=[]
        for i,rid in enumerate(sorted(wanted),1):
            exp=build_experiment(races[rid],grids[rid],cross.get(rid,{}),threshold)
            if exp is not None:
                exps.append(exp)
            if i%1000==0:
                print(f"# u={threshold:.0f} scanned={i}/{len(wanted)} usable={len(exps)}",flush=True)
        train=[e for e in exps if e.year<="2024"]
        test=[e for e in exps if e.year=="2025"]
        if not train or not test:
            raise ValueError(f"empty train/test at {threshold}: {len(train)}/{len(test)}")
        for method,cols in METHODS.items():
            coef,train_ce=fit_coefficients(train,cols)
            out=evaluate(test,cols,coef)
            print(
                f"{threshold:.0f},{method},{len(train)},{len(test)},"
                f"{sum(len(e.truth) for e in train)},{out['cells']},{coef_text(cols,coef)},"
                f"{train_ce:.6f},{out['ce']:.6f},{out['mae']:.3f},{out['log_rmse']:.4f},"
                f"{out['exact']:.4%},{out['median_spearman']:.4f},"
                f"{out['median_top_truth']:.4f},{out['median_top_pred']:.4f}",flush=True,
            )
    return 0

if __name__=="__main__":
    raise SystemExit(main())
