#!/usr/bin/env python3
"""Compare candidate high-odds tail families under the observed display cap.

This is stage 2 of the Gabaix-inspired tail diagnostic.  We do *not* extrapolate
beyond 9999.9 here.  Instead, on races whose trifecta grid has no real capped
cell, we fit each candidate to the observed interval [u, CAP) in 2022--2024 and
evaluate the same truncated conditional density in 2025.

Candidates:
  - Pareto tail
  - exponential excess tail
  - lognormal distribution truncated to [u, CAP)
  - stretched-exponential / Weibull-type tail anchored at u

Primary comparisons are 2025 mean log likelihood and prediction of higher
threshold exceedance counts.  The selected sample is conditioned on the whole
race having no 9999.9 cell, so this is a necessary pre-cap shape diagnostic,
not sufficient evidence for extrapolation above the cap.
"""
from __future__ import annotations

import math
import pathlib
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import norm

from analyze_gabaix_rank_half import load_uncapped_odds

CAP = 9999.85
THRESHOLDS = (3000.0, 5000.0, 7000.0)
TARGETS = {
    3000.0: (5000.0, 7000.0, 9000.0),
    5000.0: (7000.0, 9000.0),
    7000.0: (9000.0,),
}
EPS = 1e-12


@dataclass
class Fit:
    family: str
    u: float
    params: tuple[float, ...]
    train_ll: float


def _log1mexp_neg(x: float) -> float:
    """log(1-exp(-x)) for x>0."""
    if x <= 0:
        return -math.inf
    if x < math.log(2.0):
        return math.log(-math.expm1(-x))
    return math.log1p(-math.exp(-x))


def pareto_logpdf(x: np.ndarray, u: float, alpha: float) -> np.ndarray:
    c = CAP / u
    z = 1.0 - c ** (-alpha)
    if alpha <= 0 or z <= 0:
        return np.full_like(x, -np.inf, dtype=float)
    return math.log(alpha) + alpha * math.log(u) - (alpha + 1.0) * np.log(x) - math.log(z)


def fit_pareto(x: np.ndarray, u: float) -> Fit:
    def obj(loga: float) -> float:
        a = math.exp(loga)
        ll = pareto_logpdf(x, u, a)
        return -float(ll.sum()) if np.isfinite(ll).all() else math.inf
    res = minimize_scalar(obj, bounds=(-5, 8), method="bounded")
    a = math.exp(float(res.x))
    return Fit("pareto", u, (a,), -float(res.fun))


def exp_logpdf(x: np.ndarray, u: float, rate: float) -> np.ndarray:
    L = CAP - u
    if rate <= 0:
        return np.full_like(x, -np.inf, dtype=float)
    logz = _log1mexp_neg(rate * L)
    return math.log(rate) - rate * (x - u) - logz


def fit_exponential(x: np.ndarray, u: float) -> Fit:
    def obj(logr: float) -> float:
        r = math.exp(logr)
        ll = exp_logpdf(x, u, r)
        return -float(ll.sum()) if np.isfinite(ll).all() else math.inf
    # rate is per one odds unit; typical scale is hundreds to thousands.
    res = minimize_scalar(obj, bounds=(-12, 0), method="bounded")
    r = math.exp(float(res.x))
    return Fit("exponential", u, (r,), -float(res.fun))


def lognormal_logpdf(x: np.ndarray, u: float, mu: float, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return np.full_like(x, -np.inf, dtype=float)
    zu = (math.log(u) - mu) / sigma
    zc = (math.log(CAP) - mu) / sigma
    z = norm.cdf(zc) - norm.cdf(zu)
    if not (z > 0 and math.isfinite(z)):
        return np.full_like(x, -np.inf, dtype=float)
    lx = np.log(x)
    return (
        -np.log(x) - math.log(sigma) - 0.5 * math.log(2 * math.pi)
        - 0.5 * ((lx - mu) / sigma) ** 2 - math.log(z)
    )


def fit_lognormal(x: np.ndarray, u: float) -> Fit:
    lx = np.log(x)
    init = np.array([float(lx.mean()), math.log(max(float(lx.std()), 0.1))])
    def obj(theta: np.ndarray) -> float:
        mu, logs = map(float, theta)
        s = math.exp(logs)
        ll = lognormal_logpdf(x, u, mu, s)
        return -float(ll.sum()) if np.isfinite(ll).all() else 1e100
    res = minimize(obj, init, method="Nelder-Mead", options={"maxiter": 2500, "xatol": 1e-9, "fatol": 1e-5})
    mu, logs = map(float, res.x)
    s = math.exp(logs)
    return Fit("lognormal", u, (mu, s), -float(res.fun))


def stretch_logpdf(x: np.ndarray, u: float, a: float, k: float) -> np.ndarray:
    """S(d | d>=u)=exp(-a*((d/u)^k-1)), then truncate at CAP."""
    if a <= 0 or k <= 0:
        return np.full_like(x, -np.inf, dtype=float)
    xu = x / u
    cc = CAP / u
    H = a * (cc ** k - 1.0)
    logz = _log1mexp_neg(H)
    return (
        math.log(a) + math.log(k) - math.log(u)
        + (k - 1.0) * np.log(xu)
        - a * (xu ** k - 1.0) - logz
    )


def fit_stretched(x: np.ndarray, u: float) -> Fit:
    def obj(theta: np.ndarray) -> float:
        a, k = np.exp(theta)
        ll = stretch_logpdf(x, u, float(a), float(k))
        return -float(ll.sum()) if np.isfinite(ll).all() else 1e100
    # k=1 nests an exponential-type tail on D/u; broad starts reduce local minima risk.
    starts = [(-0.5, 0.0), (0.0, -0.7), (-1.0, 0.7), (1.0, -1.0)]
    best = None
    for start in starts:
        res = minimize(obj, np.asarray(start, dtype=float), method="Nelder-Mead", options={"maxiter": 2500, "xatol": 1e-9, "fatol": 1e-5})
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    a, k = np.exp(best.x)
    return Fit("stretched_exponential", u, (float(a), float(k)), -float(best.fun))


def logpdf(fit: Fit, x: np.ndarray) -> np.ndarray:
    if fit.family == "pareto":
        return pareto_logpdf(x, fit.u, fit.params[0])
    if fit.family == "exponential":
        return exp_logpdf(x, fit.u, fit.params[0])
    if fit.family == "lognormal":
        return lognormal_logpdf(x, fit.u, *fit.params)
    if fit.family == "stretched_exponential":
        return stretch_logpdf(x, fit.u, *fit.params)
    raise ValueError(fit.family)


def conditional_survival(fit: Fit, v: float) -> float:
    """P(D>=v | u<=D<CAP) under the fitted family."""
    u = fit.u
    if not (u <= v < CAP):
        raise ValueError((u, v))
    if fit.family == "pareto":
        a = fit.params[0]
        num = (v / u) ** (-a) - (CAP / u) ** (-a)
        den = 1.0 - (CAP / u) ** (-a)
        return num / den
    if fit.family == "exponential":
        r = fit.params[0]
        num = math.exp(-r * (v - u)) - math.exp(-r * (CAP - u))
        den = 1.0 - math.exp(-r * (CAP - u))
        return num / den
    if fit.family == "lognormal":
        mu, s = fit.params
        Fu = norm.cdf((math.log(u) - mu) / s)
        Fv = norm.cdf((math.log(v) - mu) / s)
        Fc = norm.cdf((math.log(CAP) - mu) / s)
        return (Fc - Fv) / (Fc - Fu)
    if fit.family == "stretched_exponential":
        a, k = fit.params
        Sv = math.exp(-a * ((v / u) ** k - 1.0))
        Sc = math.exp(-a * ((CAP / u) ** k - 1.0))
        return (Sv - Sc) / (1.0 - Sc)
    raise ValueError(fit.family)


def fmt_params(fit: Fit) -> str:
    if fit.family == "pareto":
        return f"alpha={fit.params[0]:.6g}"
    if fit.family == "exponential":
        return f"rate={fit.params[0]:.6g}"
    if fit.family == "lognormal":
        return f"mu={fit.params[0]:.6g};sigma={fit.params[1]:.6g}"
    return f"a={fit.params[0]:.6g};k={fit.params[1]:.6g}"


def main() -> int:
    data = pathlib.Path("데이터")
    rows = load_uncapped_odds(data)
    train_all = np.asarray([d for year, d in rows if year <= 2024], dtype=float)
    test_all = np.asarray([d for year, d in rows if year == 2025], dtype=float)

    print("# Tail-family competition under [u, 9999.85) truncation")
    print("# sample: races with no real 9999.9 cells; this does not justify above-cap extrapolation")
    print("threshold,family,train_n,test_n,params,train_mean_ll,test_mean_ll,test_vs_best_ll")
    fits_by_u: dict[float, list[Fit]] = {}
    test_ll_by_u: dict[float, dict[str, float]] = {}

    for u in THRESHOLDS:
        train = train_all[(train_all >= u) & (train_all < CAP)]
        test = test_all[(test_all >= u) & (test_all < CAP)]
        fits = [fit_pareto(train, u), fit_exponential(train, u), fit_lognormal(train, u), fit_stretched(train, u)]
        fits_by_u[u] = fits
        means = {fit.family: float(logpdf(fit, test).mean()) for fit in fits}
        test_ll_by_u[u] = means
        best = max(means.values())
        for fit in fits:
            print(
                f"{u:.0f},{fit.family},{len(train)},{len(test)},{fmt_params(fit)},"
                f"{fit.train_ll/len(train):.9f},{means[fit.family]:.9f},{means[fit.family]-best:.9f}"
            )

    print("\n# 2025 higher-threshold exceedance prediction")
    print("fit_u,target_v,family,test_n_ge_u,actual_n_ge_v,predicted_n_ge_v,relative_error,actual_over_predicted")
    family_errors: dict[str, list[float]] = {f: [] for f in ("pareto", "exponential", "lognormal", "stretched_exponential")}
    for u in THRESHOLDS:
        n_u = int(((test_all >= u) & (test_all < CAP)).sum())
        for v in TARGETS[u]:
            actual = int(((test_all >= v) & (test_all < CAP)).sum())
            for fit in fits_by_u[u]:
                pred = n_u * conditional_survival(fit, v)
                rel = abs(pred - actual) / max(actual, 1)
                family_errors[fit.family].append(rel)
                ratio = actual / pred if pred > 0 else math.inf
                print(f"{u:.0f},{v:.0f},{fit.family},{n_u},{actual},{pred:.3f},{rel:.6f},{ratio:.6f}")

    print("\n# summary")
    print("family,mean_test_ll_across_thresholds,mean_exceedance_relative_error,max_exceedance_relative_error")
    summary = []
    for family in family_errors:
        ll = float(np.mean([test_ll_by_u[u][family] for u in THRESHOLDS]))
        errs = family_errors[family]
        row = (family, ll, float(np.mean(errs)), float(np.max(errs)))
        summary.append(row)
        print(f"{family},{ll:.9f},{row[2]:.6f},{row[3]:.6f}")

    # A family is a provisional winner only if it is best on mean OOS log score
    # and no worse than 25% mean relative error in higher-threshold counts.
    best_ll = max(summary, key=lambda x: x[1])
    if best_ll[2] <= 0.25:
        verdict = f"PROVISIONAL_WINNER {best_ll[0]}"
    else:
        verdict = f"NO_STABLE_GLOBAL_FAMILY best_ll={best_ll[0]} mean_count_error={best_ll[2]:.6f}"
    print("VERDICT", verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
