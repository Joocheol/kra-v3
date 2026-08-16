#!/usr/bin/env python3
"""Stage-3 EVT diagnostic: right-truncated generalized Pareto tails.

The sample is the same entirely-uncapped 2022--2025 trifecta-race sample used
by the Rank-1/2 and tail-family diagnostics.  We fit a GPD to excesses above u
while explicitly conditioning on observation below the display cap.  This
corrects cell-level right truncation in the likelihood, but it does not undo
selection on the *whole race* having no capped cell; therefore passing remains
a necessary pre-cap diagnostic, not sufficient evidence for above-cap truth.

We test three things:
  1. GPD shape xi stability as u rises;
  2. theoretical scale shift sigma_v = sigma_u + xi*(v-u);
  3. 2022--2024 fit -> 2025 OOS likelihood and higher-threshold counts.
"""
from __future__ import annotations

import math
import pathlib
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from analyze_gabaix_rank_half import load_uncapped_odds
from analyze_tail_family_competition import fit_stretched, logpdf as family_logpdf

CAP = 9999.85
STABILITY_THRESHOLDS = (3000.0, 4000.0, 5000.0, 6000.0, 7000.0, 8000.0)
KEY_THRESHOLDS = (3000.0, 5000.0, 7000.0)
TARGETS = {
    3000.0: (5000.0, 7000.0, 9000.0),
    5000.0: (7000.0, 9000.0),
    7000.0: (9000.0,),
}


@dataclass
class GPDFit:
    u: float
    sigma: float
    xi: float
    train_ll: float


def _survival(y: float, sigma: float, xi: float) -> float:
    if y < 0:
        return 1.0
    if sigma <= 0:
        return math.nan
    if abs(xi) < 1e-7:
        return math.exp(-y / sigma)
    z = 1.0 + xi * y / sigma
    if z <= 0:
        return 0.0 if xi < 0 else math.nan
    return z ** (-1.0 / xi)


def gpd_logpdf_truncated(y: np.ndarray, sigma: float, xi: float, L: float) -> np.ndarray:
    if sigma <= 0 or L <= 0:
        return np.full_like(y, -np.inf, dtype=float)
    if abs(xi) < 1e-7:
        logz = math.log1p(-math.exp(-L / sigma))
        return -math.log(sigma) - y / sigma - logz

    z = 1.0 + xi * y / sigma
    if np.any(z <= 0):
        return np.full_like(y, -np.inf, dtype=float)
    logf = -math.log(sigma) + (-1.0 / xi - 1.0) * np.log(z)
    SL = _survival(L, sigma, xi)
    if not (0.0 <= SL < 1.0):
        return np.full_like(y, -np.inf, dtype=float)
    return logf - math.log1p(-SL)


def fit_gpd(x: np.ndarray, u: float) -> GPDFit:
    y = np.asarray(x - u, dtype=float)
    L = CAP - u
    if np.any(y < 0) or np.any(y >= L):
        raise ValueError("GPD input outside truncated support")
    base = max(float(np.mean(y)), 50.0)

    def obj(theta: np.ndarray) -> float:
        logsigma, xi = map(float, theta)
        sigma = math.exp(logsigma)
        if not (-2.0 < xi < 2.0):
            return 1e100
        ll = gpd_logpdf_truncated(y, sigma, xi, L)
        return -float(ll.sum()) if np.isfinite(ll).all() else 1e100

    starts = [
        (math.log(base), 0.0),
        (math.log(base), -0.2),
        (math.log(base), 0.2),
        (math.log(base * 2), -0.5),
        (math.log(max(base / 2, 1.0)), 0.5),
    ]
    best = None
    for start in starts:
        res = minimize(
            obj, np.asarray(start, dtype=float), method="Nelder-Mead",
            options={"maxiter": 4000, "xatol": 1e-9, "fatol": 1e-5},
        )
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    sigma = math.exp(float(best.x[0]))
    xi = float(best.x[1])
    return GPDFit(u=u, sigma=sigma, xi=xi, train_ll=-float(best.fun))


def gpd_test_ll(fit: GPDFit, x: np.ndarray) -> float:
    y = x - fit.u
    ll = gpd_logpdf_truncated(y, fit.sigma, fit.xi, CAP - fit.u)
    return float(ll.mean())


def conditional_survival(fit: GPDFit, v: float) -> float:
    if not (fit.u <= v < CAP):
        raise ValueError((fit.u, v))
    t = v - fit.u
    L = CAP - fit.u
    St = _survival(t, fit.sigma, fit.xi)
    SL = _survival(L, fit.sigma, fit.xi)
    if not (0 <= SL < 1 and 0 <= St <= 1):
        return math.nan
    return max(0.0, (St - SL) / (1.0 - SL))


def main() -> int:
    rows = load_uncapped_odds(pathlib.Path("데이터"))
    train_all = np.asarray([d for year, d in rows if year <= 2024], dtype=float)
    test_all = np.asarray([d for year, d in rows if year == 2025], dtype=float)

    print("# Right-truncated GPD threshold-stability diagnostic")
    print("threshold,train_n,test_n,sigma,xi,train_mean_ll,test_mean_ll,stretched_test_mean_ll,gpd_minus_stretched")
    fits: dict[float, GPDFit] = {}
    key_count_errors = []
    key_ll_diffs = []

    for u in STABILITY_THRESHOLDS:
        train = train_all[(train_all >= u) & (train_all < CAP)]
        test = test_all[(test_all >= u) & (test_all < CAP)]
        fit = fit_gpd(train, u)
        fits[u] = fit
        test_ll = gpd_test_ll(fit, test)
        stretched = fit_stretched(train, u)
        stretched_ll = float(family_logpdf(stretched, test).mean())
        if u in KEY_THRESHOLDS:
            key_ll_diffs.append(test_ll - stretched_ll)
        print(
            f"{u:.0f},{len(train)},{len(test)},{fit.sigma:.6f},{fit.xi:.8f},"
            f"{fit.train_ll/len(train):.9f},{test_ll:.9f},{stretched_ll:.9f},{test_ll-stretched_ll:.9f}"
        )

    print("\n# GPD threshold scale-shift check")
    print("u,v,xi_u,sigma_u,predicted_sigma_v,fitted_sigma_v,relative_error")
    scale_errors = []
    for u, v in zip(STABILITY_THRESHOLDS[:-1], STABILITY_THRESHOLDS[1:]):
        fu, fv = fits[u], fits[v]
        pred = fu.sigma + fu.xi * (v - u)
        rel = abs(pred - fv.sigma) / max(fv.sigma, 1e-12)
        scale_errors.append(rel)
        print(f"{u:.0f},{v:.0f},{fu.xi:.8f},{fu.sigma:.6f},{pred:.6f},{fv.sigma:.6f},{rel:.6f}")

    print("\n# 2025 higher-threshold exceedance prediction")
    print("fit_u,target_v,test_n_ge_u,actual_n_ge_v,predicted_n_ge_v,relative_error,actual_over_predicted")
    for u in KEY_THRESHOLDS:
        fit = fits[u]
        n_u = int(((test_all >= u) & (test_all < CAP)).sum())
        for v in TARGETS[u]:
            actual = int(((test_all >= v) & (test_all < CAP)).sum())
            pred = n_u * conditional_survival(fit, v)
            rel = abs(pred - actual) / max(actual, 1)
            key_count_errors.append(rel)
            ratio = actual / pred if pred > 0 else math.inf
            print(f"{u:.0f},{v:.0f},{n_u},{actual},{pred:.3f},{rel:.6f},{ratio:.6f}")

    xis = np.asarray([fits[u].xi for u in STABILITY_THRESHOLDS])
    xi_span = float(xis.max() - xis.min())
    mean_scale_error = float(np.mean(scale_errors))
    max_scale_error = float(np.max(scale_errors))
    mean_count_error = float(np.mean(key_count_errors))
    max_count_error = float(np.max(key_count_errors))
    mean_ll_diff = float(np.mean(key_ll_diffs))

    # Conservative pre-specified screen.  Near xi=0, relative variation is not
    # meaningful, so use absolute xi span.  Passing does not authorize actual
    # above-cap reconstruction; it only makes GPD worth carrying forward.
    pass_stability = xi_span <= 0.15 and mean_scale_error <= 0.25
    pass_prediction = mean_count_error <= 0.25
    verdict = "GPD_CANDIDATE" if pass_stability and pass_prediction else "REJECT_GLOBAL_GPD"
    print(
        "\nSUMMARY "
        f"xi_span={xi_span:.6f} mean_scale_error={mean_scale_error:.6f} "
        f"max_scale_error={max_scale_error:.6f} mean_count_error={mean_count_error:.6f} "
        f"max_count_error={max_count_error:.6f} mean_gpd_minus_stretched_test_ll={mean_ll_diff:.9f}"
    )
    print("VERDICT", verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
