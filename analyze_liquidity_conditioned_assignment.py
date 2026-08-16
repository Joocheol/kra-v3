#!/usr/bin/env python3
"""Does cross-pool assignment strength depend on tickets per state T/K?

Within real capped races, repeat pseudo-censoring at 3000/5000/7000.  Fit the
validated cross-pool feature vector (win, exacta, trio) either:
  A) once on all 2022--2024 capped races, or
  B) separately inside frozen training-period T/K quintiles.
Evaluate both on 2025 capped races.  If B materially improves CE/MAE/rank,
assignment should be liquidity-conditioned; otherwise the pooled rank model is
simpler and preferred.
"""
from __future__ import annotations

import math
import pathlib
import statistics

import numpy as np
from scipy.stats import rankdata

from analyze_cross_market import load_feasible
from analyze_masked_reconstruction import load_cross_pool_odds, load_grids, load_races, proportional_integer_allocation
from analyze_capped_regime_masking import build_experiment, fit_coefficients, softmax_probs

DATA=pathlib.Path("데이터")
THRESHOLDS=(3000.0,5000.0,7000.0)
CROSS_COLS=(2,3,4)


def rho(a,b):
    if np.all(a==a[0]) or np.all(b==b[0]): return 0.0
    return float(np.corrcoef(rankdata(a),rankdata(b))[0,1])


def eval_mixture(exps,coef_for):
    cells=tickets=exact=0; ae=lsq=ce=0.0; rhos=[]
    for e in exps:
        coef=coef_for(e)
        p=softmax_probs(e,CROSS_COLS,coef)
        pred,_=proportional_integer_allocation(e.residual,p)
        cells+=len(e.truth); tickets+=e.residual
        ae+=float(np.abs(pred-e.truth).sum())
        lsq+=float(np.square(np.log1p(pred)-np.log1p(e.truth)).sum())
        exact+=int((pred==e.truth).sum())
        ce+=-float(e.truth@np.log(np.maximum(p,1e-300)))
        rhos.append(rho(e.truth,p))
    return {
        "races":len(exps),"cells":cells,"mae":ae/cells,"logrmse":math.sqrt(lsq/cells),
        "exact":exact/cells,"ce":ce/tickets,"rho":statistics.median(rhos),
    }


def main()->int:
    races=load_races(DATA/"races.jsonl.gz")
    feasible=load_feasible(DATA/"trifecta_feasible_sets.csv.gz")
    ids={rid for rid,info in feasible.items() if int(info["capped_cells"])>0}
    grids=load_grids(DATA,races,ids); cross=load_cross_pool_odds(DATA,ids)
    L={}
    for rid in ids:
        race=races[rid]
        h=len(set(race["horses"])-set(race.get("scratched") or []))
        K=h*(h-1)*(h-2); L[rid]=int(feasible[rid]["total_tickets"])/K

    print("threshold,model,train_races,test_races,test_cells,CE,MAE,log1p_RMSE,exact,median_spearman,coef_summary")
    for u in THRESHOLDS:
        exps=[]
        for rid in sorted(ids):
            e=build_experiment(races[rid],grids[rid],cross.get(rid,{}),u)
            if e is not None: exps.append(e)
        tr=[e for e in exps if e.year<="2024"]; te=[e for e in exps if e.year=="2025"]
        pooled,_=fit_coefficients(tr,CROSS_COLS)
        out=eval_mixture(te,lambda e:pooled)
        print(f"{u:.0f},pooled,{len(tr)},{len(te)},{out['cells']},{out['ce']:.6f},{out['mae']:.3f},{out['logrmse']:.4f},{out['exact']:.4%},{out['rho']:.4f},"+";".join(f"b{i}={v:.4f}" for i,v in enumerate(pooled)))

        cuts=np.quantile([L[e.race_id] for e in tr],[.2,.4,.6,.8])
        def bid(e): return int(np.searchsorted(cuts,L[e.race_id],side="right"))
        coefs={}
        desc=[]
        for b in range(5):
            sub=[e for e in tr if bid(e)==b]
            if len(sub)<50:
                raise ValueError((u,b,len(sub)))
            c,_=fit_coefficients(sub,CROSS_COLS); coefs[b]=c
            desc.append(f"q{b+1}="+"/".join(f"{x:.3f}" for x in c))
        out2=eval_mixture(te,lambda e:coefs[bid(e)])
        print(f"{u:.0f},liquidity_quintile,{len(tr)},{len(te)},{out2['cells']},{out2['ce']:.6f},{out2['mae']:.3f},{out2['logrmse']:.4f},{out2['exact']:.4%},{out2['rho']:.4f},"+";".join(desc))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
