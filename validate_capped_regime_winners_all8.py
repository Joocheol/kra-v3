#!/usr/bin/env python3
"""All-8 external validation with capped-regime training and feature fallback.

For thresholds 7000/8000/9000, coefficients are trained only on 2022--2024
races that already contain real trifecta 9999.9 cells, using artificial masking
of visible high-odds cells.  No outcomes or real capped ticket counts enter
training.

On each 2025 official capped trifecta winner:
  * use exacta+trio score if both auxiliary grids are usable;
  * otherwise fall back to exacta-only;
  * otherwise uniform.
Predictions are projected under residual_min/mid/max, yielding a scenario
interval as well as a midpoint estimate.  This lets the two previously excluded
extreme winners remain in the external validation instead of disappearing.
"""
from __future__ import annotations

import math
import pathlib
import statistics

import numpy as np
from scipy.special import logsumexp

from analyze_cross_market import load_feasible, load_race_records
from analyze_masked_reconstruction import (
    ModelUnavailable, bounded_integer_projection, load_cross_pool_odds,
    load_grids, model_scores,
)
from analyze_capped_regime_masking import build_experiment, fit_coefficients
from check_coherence import load_month
from validate_joint_capped_winners import load_winner_truth, market_cross_pool

THRESHOLDS=(7000.0,8000.0,9000.0)
EXACTA_COL=(3,)
RICH_COL=(3,4)  # exacta_then_third, trio_then_order in capped-regime feature matrix
SCENARIOS=("residual_min","residual_mid","residual_max")


def fit_models(races,grids,cross,capped_ids,threshold):
    train=[]
    for rid in sorted(capped_ids):
        if races[rid]["date"][:4]>"2024":
            continue
        exp=build_experiment(races[rid],grids[rid],cross.get(rid,{}),threshold)
        if exp is not None:
            train.append(exp)
    rich,rich_ce=fit_coefficients(train,RICH_COL)
    ex,ex_ce=fit_coefficients(train,EXACTA_COL)
    return train,rich,rich_ce,ex,ex_ce


def probabilities_for_caps(race,market,rich_coef,exacta_coef):
    odds=market["trifecta"]
    combos=sorted(odds)
    masked=np.asarray([float(odds[c])==9999.9 for c in combos],dtype=bool)
    visible=~masked
    active=sorted(set(race["horses"])-set(race.get("scratched") or []))
    cross=market_cross_pool(market)
    dummy=np.zeros(len(combos),dtype=float)

    # Exacta is the minimum validated auxiliary signal.
    try:
        se=model_scores("exacta_then_third",combos,dummy,visible,masked,active,cross_pool=cross)
        le=np.log(se); le=le-le.mean()
    except (ModelUnavailable,ValueError,KeyError,ZeroDivisionError):
        n=int(masked.sum())
        return np.full(n,1/n),"uniform"

    # Add trio only when its complete uncensored support is usable.
    try:
        st=model_scores("trio_then_order",combos,dummy,visible,masked,active,cross_pool=cross)
        lt=np.log(st); lt=lt-lt.mean()
        logits=np.column_stack([le,lt])@rich_coef
        method="exacta+trio"
    except (ModelUnavailable,ValueError,KeyError,ZeroDivisionError):
        logits=le*float(exacta_coef[0])
        method="exacta-only"
    p=np.exp(logits-logsumexp(logits))
    return p,method


def project(info,p,scenario):
    residual=int(info[scenario])
    n=len(p)
    lo=np.zeros(n,dtype=np.int64)
    hi=np.full(n,int(info["cap_upper"]),dtype=np.int64)
    return bounded_integer_projection(residual*p,lo,hi,residual)


def main()->int:
    data=pathlib.Path("데이터")
    races=load_race_records(data/"races.jsonl.gz")
    feasible=load_feasible(data/"trifecta_feasible_sets.csv.gz")
    capped_ids={rid for rid,info in feasible.items() if int(info["capped_cells"])>0}
    grids=load_grids(data,races,capped_ids)
    cross=load_cross_pool_odds(data,capped_ids)
    truths=load_winner_truth(data/"winning_capped_payouts.csv.gz")

    by_month={}
    for threshold in THRESHOLDS:
        train,rich,rich_ce,ex,ex_ce=fit_models(races,grids,cross,capped_ids,threshold)
        print(f"# threshold={threshold:.0f} train_races={len(train)} rich_exacta={rich[0]:.6f} rich_trio={rich[1]:.6f} rich_ce={rich_ce:.6f} exacta_only={ex[0]:.6f} exacta_ce={ex_ce:.6f}")
        rows=[]
        print("race_id,actual_odds,true_tickets,method,uniform_mid,model_min,model_mid,model_max,mid_abs_error,mid_APE,scenario_interval_covers_truth")
        for truth in truths:
            rid=str(truth["race_id"]); race=races[rid]; month=race["date"][:7]
            if month not in by_month:
                by_month[month]=load_month(data,month)
            market=by_month[month][rid]; info=feasible[rid]
            odds=market["trifecta"]; combos=sorted(odds)
            masked=np.asarray([float(odds[c])==9999.9 for c in combos],dtype=bool)
            hidden=[c for c,m in zip(combos,masked) if m]
            combo=truth["combo"]
            if combo not in hidden:
                raise ValueError(f"{rid}: official winner not in capped cells")
            idx=hidden.index(combo)
            p,method=probabilities_for_caps(race,market,rich,ex)
            preds={s:int(project(info,p,s)[idx]) for s in SCENARIOS}
            up=np.full(len(hidden),1/len(hidden))
            uniform_mid=int(project(info,up,"residual_mid")[idx])
            y=int(truth["truth"]); mid=preds["residual_mid"]
            lo=min(preds.values()); hi=max(preds.values())
            cover=int(lo<=y<=hi)
            rows.append((y,uniform_mid,mid,lo,hi,method,cover))
            print(f"{rid},{float(truth['actual_odds']):.1f},{y},{method},{uniform_mid},{lo},{mid},{hi},{abs(mid-y)},{abs(mid-y)/y:.6f},{cover}")

        ua=[abs(u-y) for y,u,_,_,_,_,_ in rows]
        ma=[abs(m-y) for y,_,m,_,_,_,_ in rows]
        ur=[abs(u-y)/y for y,u,_,_,_,_,_ in rows]
        mr=[abs(m-y)/y for y,_,m,_,_,_,_ in rows]
        covers=sum(r[-1] for r in rows)
        methods={m:sum(1 for r in rows if r[5]==m) for m in ("exacta+trio","exacta-only","uniform")}
        print(
            f"SUMMARY threshold={threshold:.0f} n={len(rows)} "
            f"uniform_MAE={statistics.mean(ua):.3f} model_MAE={statistics.mean(ma):.3f} "
            f"uniform_MdAPE={statistics.median(ur):.4%} model_MdAPE={statistics.median(mr):.4%} "
            f"model_better={sum(m<u for m,u in zip(ma,ua))}/{len(rows)} "
            f"scenario_coverage={covers}/{len(rows)} methods={methods}"
        )
    return 0

if __name__=="__main__":
    raise SystemExit(main())
