#!/usr/bin/env python3
"""Condition the all-race censored GPD tail on tickets per state T/K.

Training-period (2022--2024) race-level T/K quintile cut points are frozen.
For each threshold u and liquidity bin, a right-censored GPD is fitted using:
  exact: u <= D < 9999.85
  censored: displayed 9999.9 => D >= 9999.85

2025 races are assigned to the same frozen bins. We compare the resulting
liquidity-mixture forecast against one unconditional GPD fitted to all training
races. Primary metrics are:
  * cell-weighted censored log likelihood in 2025,
  * cap-fraction prediction conditional on D>=u,
  * higher-threshold exceedance-count errors.

This remains a continuous-tail diagnostic; zero-ticket mass is not identified
here and must be handled separately in a final integer-count reconstruction.
"""
from __future__ import annotations

import math
import pathlib

import numpy as np

from analyze_all_race_censored_tail import CAP, CAP_DISPLAY, Sample, fit_gpd, gpd_ll, survival
from analyze_cross_market import load_feasible, load_race_records
from analyze_masked_reconstruction import load_grids, load_races

DATA = pathlib.Path("데이터")
THRESHOLDS=(3000.0,5000.0,7000.0)
TARGETS={3000.0:(5000.0,7000.0,CAP),5000.0:(7000.0,CAP),7000.0:(CAP,)}


def race_rows():
    race_all=load_races(DATA/"races.jsonl.gz")
    records=load_race_records(DATA/"races.jsonl.gz")
    feasible=load_feasible(DATA/"trifecta_feasible_sets.csv.gz")
    grids=load_grids(DATA,race_all,set(feasible))
    out=[]
    for rid,info in feasible.items():
        r=records[rid]
        h=len(set(r["horses"])-set(r.get("scratched") or []))
        K=h*(h-1)*(h-2)
        T=int(info["total_tickets"])
        odds=np.asarray([float(v) for _,v in grids[rid]],dtype=float)
        out.append({"rid":rid,"year":int(r["date"][:4]),"L":T/K,"K":K,"odds":odds})
    return out


def bin_id(L:float,cuts:np.ndarray)->int:
    return int(np.searchsorted(cuts,L,side="right"))


def make_sample(rows:list[dict],u:float)->Sample:
    exact=[]; cens=0
    for r in rows:
        o=r["odds"]
        cens+=int(np.sum(o==CAP_DISPLAY))
        exact.extend(o[(o>=u)&(o<CAP_DISPLAY)].tolist())
    return Sample(np.asarray(exact,dtype=float),cens)


def actual_count(rows:list[dict],v:float)->int:
    total=0
    for r in rows:
        o=r["odds"]
        if v==CAP:
            total+=int(np.sum(o==CAP_DISPLAY))
        else:
            total+=int(np.sum((o>=v)&(o<CAP_DISPLAY)))+int(np.sum(o==CAP_DISPLAY))
    return total


def main()->int:
    rows=race_rows()
    train=[r for r in rows if r["year"]<=2024]
    test=[r for r in rows if r["year"]==2025]
    cuts=np.quantile([r["L"] for r in train],[0.2,0.4,0.6,0.8])
    for r in train+test:
        r["bin"]=bin_id(r["L"],cuts)

    print("# frozen training T/K cuts",",".join(f"{x:.6f}" for x in cuts))
    print("# bin-specific fitted GPD parameters")
    print("threshold,bin,train_races,test_races,train_n,train_censored,test_n,test_censored,sigma,xi,test_mean_ll,pred_cap_fraction,actual_cap_fraction")

    aggregate=[]
    for u in THRESHOLDS:
        unconditional_train=make_sample(train,u)
        unconditional_test=make_sample(test,u)
        unfit=fit_gpd(unconditional_train,u)
        un_ll=gpd_ll(unconditional_test,u,*unfit.params)/unconditional_test.n
        un_cap=survival(unfit,CAP)
        actual_cap=unconditional_test.censored/unconditional_test.n

        total_ll=0.0; total_n=0; pred_cap_num=0.0; cap_den=0
        fits={}
        for b in range(5):
            tr=[r for r in train if r["bin"]==b]
            te=[r for r in test if r["bin"]==b]
            s_tr=make_sample(tr,u); s_te=make_sample(te,u)
            if s_tr.n<100 or s_te.n==0:
                raise ValueError((u,b,s_tr.n,s_te.n))
            fit=fit_gpd(s_tr,u); fits[b]=fit
            ll=gpd_ll(s_te,u,*fit.params)
            total_ll+=ll; total_n+=s_te.n
            pc=survival(fit,CAP)
            pred_cap_num+=s_te.n*pc; cap_den+=s_te.n
            print(f"{u:.0f},{b+1},{len(tr)},{len(te)},{len(s_tr.exact)},{s_tr.censored},{len(s_te.exact)},{s_te.censored},{fit.params[0]:.6f},{fit.params[1]:.8f},{ll/s_te.n:.9f},{pc:.8f},{s_te.censored/s_te.n:.8f}")

        cond_ll=total_ll/total_n
        cond_cap=pred_cap_num/cap_den
        aggregate.append((u,un_ll,cond_ll,un_cap,cond_cap,actual_cap,unfit.params[1]))

        print(f"AGG {u:.0f} unconditional_ll={un_ll:.9f} conditioned_ll={cond_ll:.9f} ll_gain={cond_ll-un_ll:.9f} actual_cap={actual_cap:.8f} unconditional_cap={un_cap:.8f} conditioned_cap={cond_cap:.8f} uncond_abs={abs(un_cap-actual_cap):.8f} cond_abs={abs(cond_cap-actual_cap):.8f}")

        print(f"# higher-threshold counts u={u:.0f}")
        print("target,actual,unconditional_pred,conditioned_pred,unconditional_relerr,conditioned_relerr")
        n_u=unconditional_test.n
        for v in TARGETS[u]:
            actual=actual_count(test,v)
            un_pred=n_u*survival(unfit,v)
            cond_pred=0.0
            for b in range(5):
                te=[r for r in test if r["bin"]==b]
                s_te=make_sample(te,u)
                cond_pred+=s_te.n*survival(fits[b],v)
            ue=abs(un_pred-actual)/max(actual,1)
            ce=abs(cond_pred-actual)/max(actual,1)
            print(f"{v:.2f},{actual},{un_pred:.3f},{cond_pred:.3f},{ue:.6f},{ce:.6f}")

    print("\n# aggregate summary")
    print("threshold,unconditional_test_ll,conditioned_test_ll,ll_gain,actual_cap,unconditional_cap,conditioned_cap,unconditional_cap_abs_error,conditioned_cap_abs_error,unconditional_xi")
    for u,ull,cll,uc,cc,ac,xi in aggregate:
        print(f"{u:.0f},{ull:.9f},{cll:.9f},{cll-ull:.9f},{ac:.8f},{uc:.8f},{cc:.8f},{abs(uc-ac):.8f},{abs(cc-ac):.8f},{xi:.8f}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
