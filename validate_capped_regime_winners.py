#!/usr/bin/env python3
"""Revalidate real 2025 capped winners using coefficients trained on capped races.

The previous external check trained cross-pool coefficients on entirely
uncapped races and found no improvement over uniform allocation. Stage-4 later
showed that uncapped->capped tail transfer is invalid. This script repeats the
same winner-only external diagnostic but fits the allocation coefficients only
on 2022--2024 races that themselves already contain real trifecta 9999.9 cells.

The fitting truth is still artificial masking of visible 7000--9999.8 cells;
real capped cells and race outcomes are never used for fitting.
"""
from __future__ import annotations

import pathlib
import statistics

from analyze_cross_market import load_feasible, load_race_records
from analyze_masked_reconstruction import load_cross_pool_odds, load_grids
from analyze_capped_regime_masking import build_experiment, fit_coefficients
from analyze_joint_reconstruction import FEATURE_MODELS
from check_coherence import load_month
from validate_joint_capped_winners import load_winner_truth, predict_capped

THRESHOLD=7000.0
CROSS_COLUMNS=(2,3,4)


def main()->int:
    data=pathlib.Path("데이터")
    races=load_race_records(data/"races.jsonl.gz")
    feasible=load_feasible(data/"trifecta_feasible_sets.csv.gz")
    capped_ids={rid for rid,info in feasible.items() if int(info["capped_cells"])>0}
    grids=load_grids(data,races,capped_ids)
    cross=load_cross_pool_odds(data,capped_ids)

    train=[]
    for rid in sorted(capped_ids):
        if races[rid]["date"][:4]>"2024":
            continue
        exp=build_experiment(races[rid],grids[rid],cross.get(rid,{}),THRESHOLD)
        if exp is not None:
            train.append(exp)
    coef,train_ce=fit_coefficients(train,CROSS_COLUMNS)

    truth_rows=load_winner_truth(data/"winning_capped_payouts.csv.gz")
    by_month={}
    results=[]; excluded=[]
    for truth in truth_rows:
        rid=str(truth["race_id"]); race=races[rid]; month=race["date"][:7]
        if month not in by_month:
            by_month[month]=load_month(data,month)
        market=by_month[month].get(rid); info=feasible.get(rid)
        if market is None or info is None:
            excluded.append((rid,"missing market/feasible")); continue
        try:
            uniform,joint=predict_capped(race,market,info,coef)
        except Exception as exc:
            excluded.append((rid,str(exc))); continue
        combo=truth["combo"]
        if combo not in joint:
            excluded.append((rid,"winner not capped")); continue
        y=int(truth["truth"]); u=int(uniform[combo]); j=int(joint[combo])
        results.append((rid,float(truth["actual_odds"]),y,u,j))

    print("training_regime,threshold,train_races,train_ce,coef")
    print(
        f"capped,{THRESHOLD:.0f},{len(train)},{train_ce:.6f},"+
        ";".join(f"{FEATURE_MODELS[c]}={v:.6f}" for c,v in zip(CROSS_COLUMNS,coef))
    )
    print("race_id,actual_odds,true_tickets,uniform_pred,capped_regime_pred,uniform_abs_error,model_abs_error,uniform_APE,model_APE")
    for rid,payout,y,u,j in results:
        print(f"{rid},{payout:.1f},{y},{u},{j},{abs(u-y)},{abs(j-y)},{abs(u-y)/y:.6f},{abs(j-y)/y:.6f}")
    if not results:
        raise ValueError(excluded)
    ua=[abs(u-y) for _,_,y,u,_ in results]; ja=[abs(j-y) for _,_,y,_,j in results]
    ur=[abs(u-y)/y for _,_,y,u,_ in results]; jr=[abs(j-y)/y for _,_,y,_,j in results]
    print(
        f"SUMMARY n={len(results)} excluded={len(excluded)} "
        f"uniform_MAE={statistics.mean(ua):.3f} model_MAE={statistics.mean(ja):.3f} "
        f"uniform_MdAPE={statistics.median(ur):.4%} model_MdAPE={statistics.median(jr):.4%} "
        f"uniform_maxAPE={max(ur):.4%} model_maxAPE={max(jr):.4%} "
        f"model_better={sum(j<u for j,u in zip(ja,ua))}/{len(results)}"
    )
    if excluded:
        print("EXCLUDED "+" | ".join(f"{r}:{m}" for r,m in excluded))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
