#!/usr/bin/env python3
"""Calibrate allocation uncertainty for high-odds trifecta cells.

Point softmax allocation failed spectacularly as an uncertainty model: varying
only residual_min/mid/max covered 0/8 official 2025 capped winners.  Here the
validated exacta+trio score supplies only the *mean allocation* p_i, while
integer counts are allowed to be overdispersed via a Dirichlet-multinomial:

    P ~ Dirichlet(kappa * p)
    n | P, R ~ Multinomial(R, P)

This naturally permits zero-ticket cells and produces beta-binomial marginal
prediction intervals.  kappa is fitted by likelihood on 2022--2024 capped-race
pseudo-censoring truth and evaluated on 2025 capped-race pseudo-censoring.

The goal is calibrated coverage, not merely lower MAE.  A model is useful for
real 9999.9 reconstruction only if held-out 80%/95% intervals have reasonable
coverage near the nominal levels.
"""
from __future__ import annotations

import math
import pathlib

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import gammaln
from scipy.stats import betabinom

from analyze_cross_market import load_feasible
from analyze_masked_reconstruction import load_cross_pool_odds, load_grids, load_races
from analyze_capped_regime_masking import build_experiment, fit_coefficients, softmax_probs

DATA=pathlib.Path("데이터")
THRESHOLDS=(7000.0,8000.0,9000.0)
CROSS_COLS=(2,3,4)


def dm_loglik(exp,p,kappa:float)->float:
    if kappa<=0:return -math.inf
    a=np.maximum(kappa*p,1e-12)
    n=exp.truth.astype(float); R=float(exp.residual)
    # Full DM log-likelihood, including multinomial coefficient.
    return float(
        gammaln(R+1)-gammaln(n+1).sum()
        +gammaln(kappa)-gammaln(R+kappa)
        +np.sum(gammaln(n+a)-gammaln(a))
    )


def fit_kappa(exps,coef)->tuple[float,float]:
    # Weight races equally in fitting so huge masked sets do not mechanically
    # dominate the dispersion parameter.
    def obj(logk):
        k=math.exp(float(logk))
        vals=[]
        for e in exps:
            p=softmax_probs(e,CROSS_COLS,coef)
            vals.append(dm_loglik(e,p,k))
        return -float(np.mean(vals))
    res=minimize_scalar(obj,bounds=(-5,12),method="bounded",options={"xatol":1e-5})
    k=math.exp(float(res.x))
    return k,-float(res.fun)


def coverage(exps,coef,kappa:float,level:float)->dict[str,float|int]:
    alpha=(1-level)/2
    covered=width=0.0; cells=0
    race_cov=[]
    for e in exps:
        p=softmax_probs(e,CROSS_COLS,coef)
        a=np.maximum(kappa*p,1e-10)
        b=np.maximum(kappa*(1-p),1e-10)
        lo=betabinom.ppf(alpha,e.residual,a,b)
        hi=betabinom.ppf(1-alpha,e.residual,a,b)
        ok=(e.truth>=lo)&(e.truth<=hi)
        covered+=float(ok.sum()); width+=float((hi-lo).sum()); cells+=len(e.truth)
        race_cov.append(float(ok.mean()))
    return {
        "cells":cells,"coverage":covered/cells,"mean_width":width/cells,
        "median_race_coverage":float(np.median(race_cov)),
    }


def point_metrics(exps,coef):
    ae=0.0; cells=0
    for e in exps:
        p=softmax_probs(e,CROSS_COLS,coef)
        pred=e.residual*p
        ae+=float(np.abs(pred-e.truth).sum()); cells+=len(e.truth)
    return ae/cells


def main()->int:
    races=load_races(DATA/"races.jsonl.gz")
    feasible=load_feasible(DATA/"trifecta_feasible_sets.csv.gz")
    ids={rid for rid,info in feasible.items() if int(info["capped_cells"])>0}
    grids=load_grids(DATA,races,ids); cross=load_cross_pool_odds(DATA,ids)

    print("threshold,train_races,test_races,train_cells,test_cells,coef,kappa,train_mean_DM_loglik,test_point_MAE,level,test_cell_coverage,median_race_coverage,mean_interval_width")
    for u in THRESHOLDS:
        exps=[]
        for i,rid in enumerate(sorted(ids),1):
            e=build_experiment(races[rid],grids[rid],cross.get(rid,{}),u)
            if e is not None:exps.append(e)
            if i%1000==0:print(f"# u={u:.0f} scanned={i}/{len(ids)} usable={len(exps)}",flush=True)
        train=[e for e in exps if e.year<="2024"]; test=[e for e in exps if e.year=="2025"]
        coef,_=fit_coefficients(train,CROSS_COLS)
        kappa,ll=fit_kappa(train,coef)
        mae=point_metrics(test,coef)
        ctext="/".join(f"{x:.6f}" for x in coef)
        for level in (.80,.95):
            c=coverage(test,coef,kappa,level)
            print(
                f"{u:.0f},{len(train)},{len(test)},"
                f"{sum(len(e.truth) for e in train)},{c['cells']},{ctext},{kappa:.6f},{ll:.6f},"
                f"{mae:.3f},{level:.2f},{c['coverage']:.6f},{c['median_race_coverage']:.6f},{c['mean_width']:.3f}",flush=True
            )
    return 0

if __name__=="__main__":
    raise SystemExit(main())
