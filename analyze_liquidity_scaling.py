#!/usr/bin/env python3
"""Stage-5 liquidity/state-space scaling diagnostic.

Motivated only at a high level by Gabaix et al. (2003): ask whether the scale
of trading activity helps explain extreme-price incidence. We do NOT import
their financial-market mechanism into horse racing.

For every strict-feasible 2022--2025 trifecta race:
  T = total 100-won tickets
  K = number of ordered trifecta states = h(h-1)(h-2)
  L = T/K = average tickets per state
  C/K = fraction of displayed 9999.9 states

Binomial logit models for C out of K are fitted on 2022--2024 and evaluated on
2025. The objective is scaled by total states for numerical stability.
"""
from __future__ import annotations

import pathlib

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from analyze_cross_market import load_feasible, load_race_records

DATA = pathlib.Path("데이터")


def rows() -> list[dict[str, float | int | str]]:
    races = load_race_records(DATA / "races.jsonl.gz")
    feasible = load_feasible(DATA / "trifecta_feasible_sets.csv.gz")
    out=[]
    for rid,info in feasible.items():
        race=races[rid]
        h=len(set(race["horses"])-set(race.get("scratched") or []))
        K=h*(h-1)*(h-2)
        T=int(info["total_tickets"])
        C=int(info["capped_cells"])
        if K<=0 or T<=0 or not (0<=C<=K):
            raise ValueError(rid)
        out.append({
            "race_id":rid,"year":int(race["date"][:4]),"h":h,"K":K,"T":T,"C":C,
            "L":T/K,"capfrac":C/K,
        })
    return out


def design(data:list[dict], spec:str)->np.ndarray:
    cols=[np.ones(len(data))]
    if "L" in spec:
        cols.append(np.log(np.asarray([r["L"] for r in data],dtype=float)))
    if "K" in spec:
        cols.append(np.log(np.asarray([r["K"] for r in data],dtype=float)))
    if "trend" in spec:
        cols.append(np.asarray([r["year"]-2022 for r in data],dtype=float))
    return np.column_stack(cols)


def fit_logit(data:list[dict],spec:str)->np.ndarray:
    X=design(data,spec)
    C=np.asarray([r["C"] for r in data],dtype=float)
    K=np.asarray([r["K"] for r in data],dtype=float)
    scale=float(K.sum())
    def fg(beta):
        eta=X@beta
        # Divide by total states so objective and gradient stay O(1), avoiding
        # BFGS precision-loss warnings from multi-million-cell likelihoods.
        loss=float(np.sum(K*np.logaddexp(0,eta)-C*eta)/scale)
        p=expit(eta)
        grad=(X.T@(K*p-C))/scale
        return loss,grad
    res=minimize(
        lambda b:fg(b)[0],np.zeros(X.shape[1]),jac=lambda b:fg(b)[1],
        method="BFGS",options={"gtol":1e-9,"maxiter":1000},
    )
    if not res.success and np.linalg.norm(res.jac)>1e-6:
        raise RuntimeError(f"{spec}: {res.message}; |grad|={np.linalg.norm(res.jac):.3g}")
    return np.asarray(res.x)


def evaluate(data:list[dict],spec:str,beta:np.ndarray)->dict[str,float]:
    X=design(data,spec)
    p=expit(X@beta)
    C=np.asarray([r["C"] for r in data],dtype=float)
    K=np.asarray([r["K"] for r in data],dtype=float)
    y=C/K
    agg_actual=float(C.sum()/K.sum())
    agg_pred=float((K*p).sum()/K.sum())
    race_mae=float(np.mean(np.abs(y-p)))
    ll=float(np.sum(C*np.log(np.maximum(p,1e-300))+(K-C)*np.log(np.maximum(1-p,1e-300)))/K.sum())
    return {"actual":agg_actual,"pred":agg_pred,"abs":abs(agg_pred-agg_actual),"mae":race_mae,"ll":ll}


def coef_names(spec:str)->list[str]:
    names=["intercept"]
    if "L" in spec:names.append("log_T_per_state")
    if "K" in spec:names.append("log_K")
    if "trend" in spec:names.append("year_trend")
    return names


def main()->int:
    data=rows()
    train=[r for r in data if r["year"]<=2024]
    test=[r for r in data if r["year"]==2025]
    print("# year summaries")
    print("year,races,states,tickets,capped_cells,cell_weighted_cap_fraction,median_T_per_state,median_race_cap_fraction")
    for year in (2022,2023,2024,2025):
        g=[r for r in data if r["year"]==year]
        states=sum(r["K"] for r in g); tickets=sum(r["T"] for r in g); caps=sum(r["C"] for r in g)
        print(f"{year},{len(g)},{states},{tickets},{caps},{caps/states:.8f},{np.median([r['L'] for r in g]):.6f},{np.median([r['capfrac'] for r in g]):.8f}")

    specs=("intercept","L","LK","LKtrend")
    print("\n# 2022-2024 fit -> 2025 OOS cap incidence")
    print("spec,coefficients,actual_cap_fraction,predicted_cap_fraction,aggregate_abs_error,race_MAE,cell_weighted_log_score")
    results={}
    for spec in specs:
        beta=fit_logit(train,spec)
        ev=evaluate(test,spec,beta)
        results[spec]=ev
        coefs=";".join(f"{n}={v:.6f}" for n,v in zip(coef_names(spec),beta))
        print(f"{spec},{coefs},{ev['actual']:.8f},{ev['pred']:.8f},{ev['abs']:.8f},{ev['mae']:.8f},{ev['ll']:.9f}")

    qs=np.quantile([r["L"] for r in train],[0.2,0.4,0.6,0.8])
    def binid(x): return int(np.searchsorted(qs,x,side="right"))+1
    print("\n# liquidity bins defined from 2022-2024 T/K quintiles")
    print("sample,bin,races,median_T_per_state,cell_weighted_cap_fraction")
    for label,g in (("train",train),("test2025",test)):
        for b in range(1,6):
            sub=[r for r in g if binid(r["L"])==b]
            states=sum(r["K"] for r in sub); caps=sum(r["C"] for r in sub)
            if not sub or states==0:
                print(f"{label},{b},0,nan,nan")
            else:
                print(f"{label},{b},{len(sub)},{np.median([r['L'] for r in sub]):.6f},{caps/states:.8f}")

    best=min(specs,key=lambda s:results[s]["abs"])
    print(f"\nVERDICT best_2025_aggregate={best} abs_error={results[best]['abs']:.8f}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
