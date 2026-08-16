#!/usr/bin/env python3
"""Null-referenced inference for the allocation-free capped-tail calibration test.

Claude review correctly noted that resampling observed dates estimates sampling
uncertainty around the observed statistic; it is not itself a null-reference
test for a rare event.  This script therefore reports three one-sided tests for
H1: realised cap-hit frequency is below accounting ticket mass (sum Y < sum Q):

1. exact lower-tail Poisson-binomial p-value under race independence;
2. date-cluster sandwich normal score test;
3. date-cluster Rademacher multiplier score bootstrap, centered on the null
   because the score contributions are S_g = sum_{i in g}(Y_i-Q_i).

A 5% 'robust directional rejection' is allowed only if all three p-values are
below .05.  This makes the previously borderline residual_min case explicitly
conservative rather than selecting whichever inference is most favorable.
"""
from __future__ import annotations

import math
import pathlib
from collections import defaultdict

import numpy as np

from analyze_flb_tail import DATA, SCENARIOS, load_feasible, load_outcomes

DRAWS = 100_000
SEED = 20260816


def poisson_binomial_lower(probs: np.ndarray, observed: int) -> float:
    """Exact P(S<=observed) using DP truncated at observed successes."""
    if observed < 0:
        return 0.0
    # dp[k] = P(exactly k successes), tracked only through observed.
    dp = np.zeros(observed + 1, dtype=float)
    dp[0] = 1.0
    for p in probs:
        # descending update avoids copying and excludes mass above observed.
        upper = min(observed, len(probs))
        for k in range(upper, 0, -1):
            dp[k] = dp[k] * (1.0 - p) + dp[k - 1] * p
        dp[0] *= 1.0 - p
    return float(dp.sum())


def inference(rows, feasible, scenario: str, seed: int) -> dict[str, float | int]:
    merged=[]
    for row in rows:
        info=feasible.get(str(row["race_id"]))
        if info is not None:
            merged.append((str(row["date"]),int(row["y"]),float(info[scenario])))
    if not merged:
        raise ValueError("empty sample")

    y=np.asarray([v[1] for v in merged],dtype=float)
    q=np.asarray([v[2] for v in merged],dtype=float)
    observed=int(y.sum()); expected=float(q.sum())
    exact_p=poisson_binomial_lower(q,observed)

    by_date=defaultdict(list)
    for d,yy,qq in merged:
        by_date[d].append((yy,qq))
    dates=sorted(by_date)
    sg=np.asarray([sum(yy-qq for yy,qq in by_date[d]) for d in dates],dtype=float)
    # H0 score total is sum(Y-Q).  Cluster sandwich variance of the score sum.
    G=len(sg)
    var=(G/(G-1))*float(sg@sg) if G>1 else math.nan
    z=float(sg.sum()/math.sqrt(var)) if var>0 else math.nan
    p_cluster=0.5*math.erfc(-z/math.sqrt(2)) if math.isfinite(z) else math.nan

    # Null-centered wild score bootstrap. Rademacher multipliers preserve each
    # date cluster's score magnitude while imposing E[S_g*]=0 under H0.
    rng=np.random.default_rng(seed)
    # Batch to avoid a 100k x 600 persistent matrix.
    extreme=0; done=0
    denom=math.sqrt(var)
    obs_t=float(sg.sum()/denom)
    batch=5000
    while done<DRAWS:
        m=min(batch,DRAWS-done)
        w=rng.integers(0,2,size=(m,G),dtype=np.int8)*2-1
        tb=(w@sg)/denom
        extreme+=int(np.sum(tb<=obs_t+1e-15))
        done+=m
    p_wild=(extreme+1)/(DRAWS+1)

    conservative=max(exact_p,p_cluster,p_wild)
    return {
        "races":len(merged),"dates":G,"observed":observed,"expected":expected,
        "oe":observed/expected,"exact_p":exact_p,"z":z,"cluster_p":p_cluster,
        "wild_p":p_wild,"conservative_p":conservative,
        "robust_reject":int(exact_p<.05 and p_cluster<.05 and p_wild<.05),
    }


def main()->int:
    feasible=load_feasible(DATA/"trifecta_feasible_sets.csv.gz")
    outcomes=load_outcomes(DATA/"outcome_robustness.csv.gz")
    samples=(
        ("2025",lambda y:y=="2025"),
        ("2022--2024",lambda y:"2022"<=y<="2024"),
        ("2022--2025",lambda y:"2022"<=y<="2025"),
    )
    print("sample,scenario,races,dates,observed,expected,O_over_E,exact_poisson_binomial_p,cluster_z,cluster_normal_p,wild_cluster_p,conservative_p,robust_directional_reject_5pct")
    k=0
    for name,keep in samples:
        sub=[r for r in outcomes if keep(str(r["year"]))]
        for scenario in SCENARIOS:
            r=inference(sub,feasible,scenario,SEED+k); k+=1
            print(
                f"{name},{scenario},{r['races']},{r['dates']},{r['observed']},"
                f"{r['expected']:.6f},{r['oe']:.6f},{r['exact_p']:.6f},"
                f"{r['z']:.4f},{r['cluster_p']:.6f},{r['wild_p']:.6f},"
                f"{r['conservative_p']:.6f},{r['robust_reject']}"
            )
    return 0

if __name__=="__main__":
    raise SystemExit(main())
