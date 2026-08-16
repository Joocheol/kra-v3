#!/usr/bin/env python3
"""Calibration-null simulation for the payout-band O/E curve.

The odds bands are defined by the same market prices whose ticket mass forms the
null probabilities.  To check whether the observed non-monotone O/E pattern is
merely a binning artefact, freeze every race's band-mass vector m_i and impose
H0: the winning band is a categorical draw with probabilities m_i.

The aggregate winner-count vector has mean sum m_i and covariance
sum[diag(m_i)-m_i m_i'].  We simulate its multivariate Gaussian limit (10 bands,
9,671 races) to obtain marginal directional p-values, a simultaneous max-|z|
reference, and two descriptive contrasts:
  * cap minus 3000--9999.8 pre-cap tail;
  * 300--3000 hump minus 10--100 lower-odds region.

This addresses endogenous-band geometry under the calibration null.  It does
not replace the separate date-cluster / rare-event inference, because the null
simulation assumes independent race outcomes conditional on the frozen masses.
"""
from __future__ import annotations

import pathlib
from collections import defaultdict

import numpy as np

from analyze_cross_market import load_feasible, load_race_records
from analyze_flb_curve import LABELS, race_band_mass
from check_coherence import load_month

DATA=pathlib.Path("데이터")
DRAWS=200_000
SEED=20260816


def ratio_of_sums(x,idx,E):
    return x[...,idx].sum(axis=-1)/E[idx].sum()


def main()->int:
    races=load_race_records(DATA/"races.jsonl.gz")
    feasible=load_feasible(DATA/"trifecta_feasible_sets.csv.gz")
    months={}; masses=[]; winner=[]
    for j,rid in enumerate(sorted(feasible),1):
        race=races[rid]; month=race["date"][:7]
        if month not in months: months[month]=load_month(DATA,month)
        market=months[month][rid]
        m,b=race_band_mass(race,market,feasible[rid])
        masses.append(m); winner.append(b)
        if j%1000==0: print(f"# loaded {j}/{len(feasible)}",flush=True)
    M=np.vstack(masses); n=len(M); B=M.shape[1]
    O=np.bincount(np.asarray(winner),minlength=B).astype(float)
    E=M.sum(axis=0)
    cov=np.zeros((B,B),dtype=float)
    for m in M:
        cov+=np.diag(m)-np.outer(m,m)
    sd=np.sqrt(np.diag(cov)); z=(O-E)/sd

    # Covariance is singular because counts sum to n.  numpy can sample from
    # positive-semidefinite covariance directly; tiny numerical negatives are
    # tolerated by the eigen/SVD implementation.
    rng=np.random.default_rng(SEED)
    sim=rng.multivariate_normal(E,cov,size=DRAWS,check_valid="ignore",method="svd")
    simz=(sim-E)/sd
    maxabs=np.max(np.abs(simz),axis=1)
    simultaneous_95=float(np.quantile(maxabs,.95))

    print("band,observed,expected,O_over_E,z,null_directional_p,simultaneous_95_zcrit,simultaneous_flag")
    for b,label in enumerate(LABELS):
        if O[b]<E[b]: p=(1+np.sum(sim[:,b]<=O[b]))/(DRAWS+1)
        else: p=(1+np.sum(sim[:,b]>=O[b]))/(DRAWS+1)
        flag=int(abs(z[b])>simultaneous_95)
        print(f"{label},{int(O[b])},{E[b]:.6f},{O[b]/E[b]:.6f},{z[b]:.4f},{p:.6f},{simultaneous_95:.4f},{flag}")

    # Pre-cap 3000--9999.8 = labels indices 6,7,8. Cap = index 9.
    pre=np.array([6,7,8]); cap=np.array([9])
    obs_capdiff=ratio_of_sums(O,cap,E)-ratio_of_sums(O,pre,E)
    sim_capdiff=ratio_of_sums(sim,cap,E)-ratio_of_sums(sim,pre,E)
    p_cap=(1+np.sum(sim_capdiff<=obs_capdiff))/(DRAWS+1)

    # 300--3000 (4,5) minus 10--100 (1,2): exploratory non-monotone hump.
    hump=np.array([4,5]); low=np.array([1,2])
    obs_hump=ratio_of_sums(O,hump,E)-ratio_of_sums(O,low,E)
    sim_hump=ratio_of_sums(sim,hump,E)-ratio_of_sums(sim,low,E)
    p_hump=(1+np.sum(sim_hump>=obs_hump))/(DRAWS+1)

    print("\nCONTRAST,name,observed,null_mean,null_sd,directional_p")
    print(f"CONTRAST,cap_minus_3000_9999,{obs_capdiff:.6f},{sim_capdiff.mean():.6f},{sim_capdiff.std():.6f},{p_cap:.6f}")
    print(f"CONTRAST,300_3000_minus_10_100,{obs_hump:.6f},{sim_hump.mean():.6f},{sim_hump.std():.6f},{p_hump:.6f}")
    print(f"SUMMARY races={n} draws={DRAWS} simultaneous_95_max_abs_z={simultaneous_95:.6f}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
