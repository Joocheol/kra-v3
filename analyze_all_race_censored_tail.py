#!/usr/bin/env python3
"""Fit high-odds tail families to *all* races using right-censoring at 9999.9.

This fixes the central selection problem revealed by the Gabaix/EVT stages.
Entirely uncapped races are no longer the training population.  For every
strict-feasible 2022--2025 trifecta race:

* displayed D < 9999.9 is an exact tail observation;
* displayed 9999.9 is a right-censored observation D >= 9999.85.

For a threshold u, likelihood is conditional on D>=u.  Models are fitted on
2022--2024 and scored on 2025, including the censored observations.  Because
all capped cells are retained, this test directly asks whether a candidate
family predicts the frequency of hitting the display cap and the shape below
it without selecting away heavy-tail races.
"""
from __future__ import annotations

import math
import pathlib
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import norm

from analyze_cross_market import load_feasible
from analyze_masked_reconstruction import load_grids, load_races

CAP_DISPLAY = 9999.9
CAP = 9999.85
THRESHOLDS = (3000.0, 5000.0, 7000.0)
TARGETS = {
    3000.0: (5000.0, 7000.0, CAP),
    5000.0: (7000.0, CAP),
    7000.0: (CAP,),
}


@dataclass
class Sample:
    exact: np.ndarray
    censored: int

    @property
    def n(self) -> int:
        return len(self.exact) + self.censored


@dataclass
class Fit:
    family: str
    u: float
    params: tuple[float, ...]
    train_ll: float


def build_samples(data: pathlib.Path) -> tuple[dict[float, Sample], dict[float, Sample]]:
    races = load_races(data / "races.jsonl.gz")
    feasible = load_feasible(data / "trifecta_feasible_sets.csv.gz")
    grids = load_grids(data, races, set(feasible))
    train_exact = {u: [] for u in THRESHOLDS}
    test_exact = {u: [] for u in THRESHOLDS}
    train_cap = {u: 0 for u in THRESHOLDS}
    test_cap = {u: 0 for u in THRESHOLDS}

    for rid, values in grids.items():
        year = int(races[rid]["date"][:4])
        target_exact = train_exact if year <= 2024 else test_exact
        target_cap = train_cap if year <= 2024 else test_cap
        for _, raw in values:
            d = float(raw)
            if d == CAP_DISPLAY:
                for u in THRESHOLDS:
                    target_cap[u] += 1
            else:
                for u in THRESHOLDS:
                    if d >= u:
                        target_exact[u].append(d)

    train = {u: Sample(np.asarray(train_exact[u], dtype=float), train_cap[u]) for u in THRESHOLDS}
    test = {u: Sample(np.asarray(test_exact[u], dtype=float), test_cap[u]) for u in THRESHOLDS}
    return train, test


# ---------- Pareto ---------------------------------------------------------
def pareto_ll(sample: Sample, u: float, alpha: float) -> float:
    if alpha <= 0:
        return -math.inf
    exact_ll = (
        len(sample.exact) * (math.log(alpha) + alpha * math.log(u))
        - (alpha + 1.0) * float(np.log(sample.exact).sum())
    )
    cens_ll = sample.censored * (-alpha * math.log(CAP / u))
    return exact_ll + cens_ll


def fit_pareto(sample: Sample, u: float) -> Fit:
    res = minimize_scalar(lambda z: -pareto_ll(sample, u, math.exp(z)), bounds=(-6, 8), method="bounded")
    a = math.exp(float(res.x))
    return Fit("pareto", u, (a,), -float(res.fun))


# ---------- Exponential excess -------------------------------------------
def exp_ll(sample: Sample, u: float, rate: float) -> float:
    if rate <= 0:
        return -math.inf
    exact_ll = len(sample.exact) * math.log(rate) - rate * float((sample.exact - u).sum())
    cens_ll = -sample.censored * rate * (CAP - u)
    return exact_ll + cens_ll


def fit_exponential(sample: Sample, u: float) -> Fit:
    res = minimize_scalar(lambda z: -exp_ll(sample, u, math.exp(z)), bounds=(-13, 0), method="bounded")
    r = math.exp(float(res.x))
    return Fit("exponential", u, (r,), -float(res.fun))


# ---------- Lognormal conditional on D>=u --------------------------------
def lognormal_components(x: np.ndarray, u: float, mu: float, sigma: float) -> tuple[np.ndarray, float]:
    if sigma <= 0:
        return np.full_like(x, -np.inf), -math.inf
    Su = norm.sf((math.log(u) - mu) / sigma)
    Sc = norm.sf((math.log(CAP) - mu) / sigma)
    if not (Su > 0 and Sc > 0 and Sc <= Su):
        return np.full_like(x, -np.inf), -math.inf
    lx = np.log(x)
    logf = (
        -np.log(x) - math.log(sigma) - 0.5 * math.log(2 * math.pi)
        - 0.5 * ((lx - mu) / sigma) ** 2 - math.log(Su)
    )
    logSc = math.log(Sc) - math.log(Su)
    return logf, logSc


def lognormal_ll(sample: Sample, u: float, mu: float, sigma: float) -> float:
    logf, logSc = lognormal_components(sample.exact, u, mu, sigma)
    if not np.isfinite(logf).all() or not math.isfinite(logSc):
        return -math.inf
    return float(logf.sum()) + sample.censored * logSc


def fit_lognormal(sample: Sample, u: float) -> Fit:
    lx = np.log(sample.exact)
    init = np.array([float(lx.mean()), math.log(max(float(lx.std()), 0.2))])
    def obj(theta: np.ndarray) -> float:
        mu, logs = map(float, theta)
        return -lognormal_ll(sample, u, mu, math.exp(logs))
    best = None
    for start in (init, np.array([math.log(u), 0.8]), np.array([math.log(u/2), 1.2])):
        res = minimize(obj, start, method="Nelder-Mead", options={"maxiter":3000,"xatol":1e-9,"fatol":1e-5})
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    mu, logs = map(float, best.x)
    return Fit("lognormal", u, (mu, math.exp(logs)), -float(best.fun))


# ---------- Stretched exponential -----------------------------------------
def stretch_survival(d: float, u: float, a: float, k: float) -> float:
    return math.exp(-a * ((d / u) ** k - 1.0))


def stretch_ll(sample: Sample, u: float, a: float, k: float) -> float:
    if a <= 0 or k <= 0:
        return -math.inf
    x = sample.exact
    xu = x / u
    logf = (
        math.log(a) + math.log(k) - math.log(u)
        + (k - 1.0) * np.log(xu)
        - a * (xu ** k - 1.0)
    )
    cens = sample.censored * math.log(stretch_survival(CAP, u, a, k))
    return float(logf.sum()) + cens


def fit_stretched(sample: Sample, u: float) -> Fit:
    def obj(theta: np.ndarray) -> float:
        a, k = np.exp(theta)
        return -stretch_ll(sample, u, float(a), float(k))
    starts = [(-0.5,0.0),(0.0,-0.7),(-1.0,0.7),(1.0,-1.0)]
    best = None
    for start in starts:
        res = minimize(obj, np.asarray(start,dtype=float), method="Nelder-Mead", options={"maxiter":3000,"xatol":1e-9,"fatol":1e-5})
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    a, k = np.exp(best.x)
    return Fit("stretched_exponential", u, (float(a),float(k)), -float(best.fun))


# ---------- GPD ------------------------------------------------------------
def gpd_survival(y: float, sigma: float, xi: float) -> float:
    if abs(xi) < 1e-7:
        return math.exp(-y / sigma)
    z = 1.0 + xi * y / sigma
    if z <= 0:
        return 0.0 if xi < 0 else math.nan
    return z ** (-1.0/xi)


def gpd_ll(sample: Sample, u: float, sigma: float, xi: float) -> float:
    if sigma <= 0:
        return -math.inf
    y = sample.exact - u
    if abs(xi) < 1e-7:
        exact = -len(y)*math.log(sigma) - float(y.sum())/sigma
    else:
        z = 1.0 + xi*y/sigma
        if np.any(z <= 0):
            return -math.inf
        exact = -len(y)*math.log(sigma) + (-1.0/xi-1.0)*float(np.log(z).sum())
    Sc = gpd_survival(CAP-u, sigma, xi)
    if not (Sc > 0 and Sc <= 1):
        return -math.inf
    return exact + sample.censored*math.log(Sc)


def fit_gpd(sample: Sample, u: float) -> Fit:
    base = max(float(np.mean(sample.exact-u)), 100.0)
    def obj(theta: np.ndarray) -> float:
        logs, xi = map(float,theta)
        if not (-1.5 < xi < 2.0):
            return 1e100
        ll = gpd_ll(sample,u,math.exp(logs),xi)
        return -ll if math.isfinite(ll) else 1e100
    starts=[(math.log(base),0.0),(math.log(base),0.2),(math.log(base),-0.2),(math.log(base*2),0.5)]
    best=None
    for start in starts:
        res=minimize(obj,np.asarray(start),method="Nelder-Mead",options={"maxiter":4000,"xatol":1e-9,"fatol":1e-5})
        if best is None or res.fun<best.fun:
            best=res
    assert best is not None
    return Fit("gpd",u,(math.exp(float(best.x[0])),float(best.x[1])),-float(best.fun))


def sample_ll(fit: Fit, sample: Sample) -> float:
    if fit.family=="pareto": return pareto_ll(sample,fit.u,fit.params[0])
    if fit.family=="exponential": return exp_ll(sample,fit.u,fit.params[0])
    if fit.family=="lognormal": return lognormal_ll(sample,fit.u,*fit.params)
    if fit.family=="stretched_exponential": return stretch_ll(sample,fit.u,*fit.params)
    if fit.family=="gpd": return gpd_ll(sample,fit.u,*fit.params)
    raise ValueError(fit.family)


def survival(fit: Fit, d: float) -> float:
    u=fit.u
    if fit.family=="pareto": return (d/u)**(-fit.params[0])
    if fit.family=="exponential": return math.exp(-fit.params[0]*(d-u))
    if fit.family=="lognormal":
        mu,s=fit.params
        return norm.sf((math.log(d)-mu)/s)/norm.sf((math.log(u)-mu)/s)
    if fit.family=="stretched_exponential": return stretch_survival(d,u,*fit.params)
    if fit.family=="gpd": return gpd_survival(d-u,*fit.params)
    raise ValueError(fit.family)


def params_text(fit: Fit) -> str:
    if fit.family=="pareto": return f"alpha={fit.params[0]:.6g}"
    if fit.family=="exponential": return f"rate={fit.params[0]:.6g}"
    if fit.family=="lognormal": return f"mu={fit.params[0]:.6g};sigma={fit.params[1]:.6g}"
    if fit.family=="stretched_exponential": return f"a={fit.params[0]:.6g};k={fit.params[1]:.6g}"
    return f"sigma={fit.params[0]:.6g};xi={fit.params[1]:.6g}"


def endpoint(fit: Fit) -> float:
    if fit.family=="gpd" and fit.params[1] < 0:
        return fit.u - fit.params[0]/fit.params[1]
    return math.inf


def main() -> int:
    train,test=build_samples(pathlib.Path("데이터"))
    print("# All-race censored-tail family comparison")
    print("threshold,family,train_exact,train_censored,test_exact,test_censored,params,train_mean_ll,test_mean_ll,pred_cap_fraction,actual_cap_fraction,cap_fraction_abs_error,endpoint")
    fits_by_u={}
    summary=[]
    for u in THRESHOLDS:
        fits=[fit_pareto(train[u],u),fit_exponential(train[u],u),fit_lognormal(train[u],u),fit_stretched(train[u],u),fit_gpd(train[u],u)]
        fits_by_u[u]=fits
        actual_cap=test[u].censored/test[u].n
        for fit in fits:
            tll=sample_ll(fit,test[u])/test[u].n
            pred_cap=survival(fit,CAP)
            err=abs(pred_cap-actual_cap)
            ep=endpoint(fit)
            eptext="inf" if math.isinf(ep) else f"{ep:.1f}"
            print(f"{u:.0f},{fit.family},{len(train[u].exact)},{train[u].censored},{len(test[u].exact)},{test[u].censored},{params_text(fit)},{fit.train_ll/train[u].n:.9f},{tll:.9f},{pred_cap:.8f},{actual_cap:.8f},{err:.8f},{eptext}")
            summary.append((u,fit.family,tll,err))

    print("\n# 2025 exceedance-count prediction including real capped cells")
    print("fit_u,target,family,test_n_ge_u,actual_n_ge_target,predicted_n_ge_target,relative_error")
    errors={f:[] for f in ("pareto","exponential","lognormal","stretched_exponential","gpd")}
    # Exact + censored observations at u; for targets below CAP, every capped
    # cell is known to exceed target and therefore counts in the actual total.
    for u in THRESHOLDS:
        n_u=test[u].n
        for v in TARGETS[u]:
            if v==CAP:
                actual=test[u].censored
            else:
                actual=int(np.sum(test[u].exact>=v))+test[u].censored
            for fit in fits_by_u[u]:
                pred=n_u*survival(fit,v)
                rel=abs(pred-actual)/max(actual,1)
                errors[fit.family].append(rel)
                print(f"{u:.0f},{v:.2f},{fit.family},{n_u},{actual},{pred:.3f},{rel:.6f}")

    print("\n# summary")
    print("family,mean_test_ll,mean_count_relative_error,max_count_relative_error,mean_cap_fraction_abs_error")
    rows=[]
    for family in errors:
        lls=[x[2] for x in summary if x[1]==family]
        caperrs=[x[3] for x in summary if x[1]==family]
        row=(family,float(np.mean(lls)),float(np.mean(errors[family])),float(np.max(errors[family])),float(np.mean(caperrs)))
        rows.append(row)
        print(f"{family},{row[1]:.9f},{row[2]:.6f},{row[3]:.6f},{row[4]:.8f}")
    best=max(rows,key=lambda x:x[1])
    print("VERDICT BEST_OOS_CENSORED_LL",best[0])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
