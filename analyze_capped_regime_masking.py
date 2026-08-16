#!/usr/bin/env python3
"""Pseudo-censor visible high-odds cells *within real capped trifecta races*.

This is the key follow-up to the rank-size transfer rejection.  Training and
validation are both restricted to races that already contain real 9999.9
trifecta cells.  Those genuinely capped cells are excluded from both features
and evaluation because their true ticket counts are unknown.

For each virtual threshold u=3000/5000/7000, only cells with
    u <= displayed odds < 9999.9
whose displayed-odds accounting interval identifies one exact ticket count are
artificially masked.  Lower uncapped trifecta cells (<u) supply same-pool
features; win/exacta/trio grids supply auxiliary features.  The total ticket
count of the artificial masked set is known from its exact displayed-odds
truth, so models are compared on how they allocate that total within the set.

Coefficients are fitted on capped races from 2022--2024 and evaluated on capped
races from 2025.  Finishing orders are never used for fitting.
"""
from __future__ import annotations

import math
import pathlib
import statistics
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from scipy.stats import rankdata

from analyze_cross_market import load_feasible
from analyze_masked_reconstruction import (
    ModelUnavailable,
    _won,
    load_cross_pool_odds,
    load_grids,
    load_races,
    model_scores,
    proportional_integer_allocation,
)
from kra.feasible import displayed_ticket_interval

THRESHOLDS = (3000.0, 5000.0, 7000.0)
FEATURE_MODELS = (
    "position_independent",
    "prefix_uniform_third",
    "win_harville",
    "exacta_then_third",
    "trio_then_order",
)
METHODS = {
    "uniform": (),
    "same_pool_joint": (0, 1),
    "cross_pool_joint": (2, 3, 4),
    "all_joint": (0, 1, 2, 3, 4),
}
RIDGE = 1e-4
MAX_COEF = 5.0
CAP = 9999.9


@dataclass
class Experiment:
    race_id: str
    year: str
    features: np.ndarray
    truth: np.ndarray
    residual: int


def proxy_count(sales: int, odds: float) -> float:
    """Continuous accounting center used only as a same-pool feature weight."""
    total = sales // 100
    return 0.73 * total / odds


def build_experiment(
    race: dict,
    values: list[tuple[tuple[int, int, int], Decimal]],
    cross_pool: dict[str, dict[tuple[int, ...], float]],
    threshold: float,
) -> Experiment | None:
    sales = _won(race["sales"]["삼쌍승식"])
    combos = [combo for combo, _ in values]
    odds = np.asarray([float(value) for _, value in values], dtype=float)

    # Artificial truth: visible high-odds cells only. Real capped cells are
    # never masked truth because their ticket count is exactly what is unknown.
    candidate = (odds >= threshold) & (odds < CAP)
    if not candidate.any():
        return None

    truth_global = np.full(len(values), -1, dtype=np.int64)
    point = np.zeros(len(values), dtype=bool)
    for i in np.flatnonzero(candidate):
        interval = displayed_ticket_interval(sales, Decimal(str(odds[i])))
        if interval and len(interval) == 1:
            point[i] = True
            truth_global[i] = interval.start
    masked = candidate & point
    if masked.sum() < 3:
        return None

    # Inputs deliberately exclude both the pseudo-masked known tail and every
    # genuine 9999.9 cell. Only lower observed trifecta cells inform same-pool
    # marginals/prefixes.
    visible = odds < threshold
    counts_proxy = np.zeros(len(values), dtype=float)
    for i in np.flatnonzero(visible):
        counts_proxy[i] = proxy_count(sales, odds[i])

    active = sorted(set(race["horses"]) - set(race.get("scratched") or []))
    columns = []
    for model in FEATURE_MODELS:
        try:
            score = model_scores(
                model, combos, counts_proxy, visible, masked, active,
                cross_pool=cross_pool,
            )
        except ModelUnavailable:
            return None
        if np.any(score <= 0) or not np.isfinite(score).all():
            return None
        ls = np.log(score)
        columns.append(ls - ls.mean())

    truth = truth_global[masked].astype(float)
    residual = int(truth.sum())
    if residual <= 0:
        return None
    return Experiment(
        race_id=race["race_id"],
        year=race["date"][:4],
        features=np.column_stack(columns),
        truth=truth,
        residual=residual,
    )


def softmax_probs(exp: Experiment, columns: tuple[int, ...], coef: np.ndarray) -> np.ndarray:
    if not columns:
        return np.full(len(exp.truth), 1.0 / len(exp.truth))
    logits = exp.features[:, columns] @ coef
    return np.exp(logits - logsumexp(logits))


def fit_coefficients(experiments: list[Experiment], columns: tuple[int, ...]) -> tuple[np.ndarray, float]:
    total_tickets = sum(exp.residual for exp in experiments)
    if not columns:
        ce = sum(exp.residual * math.log(len(exp.truth)) for exp in experiments) / total_tickets
        return np.empty(0), ce

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        loss = 0.0
        grad = np.zeros_like(theta)
        for exp in experiments:
            x = exp.features[:, columns]
            logits = x @ theta
            lse = logsumexp(logits)
            probs = np.exp(logits - lse)
            loss += exp.residual * lse - float(exp.truth @ logits)
            grad += exp.residual * (probs @ x) - exp.truth @ x
        loss = loss / total_tickets + RIDGE * float(theta @ theta)
        grad = grad / total_tickets + 2 * RIDGE * theta
        return loss, grad

    fit = minimize(
        lambda t: objective(t)[0], np.full(len(columns), 0.1),
        jac=lambda t: objective(t)[1], method="L-BFGS-B",
        bounds=[(0.0, MAX_COEF)] * len(columns),
        options={"maxiter": 300, "ftol": 1e-12, "gtol": 1e-8},
    )
    if not fit.success:
        raise RuntimeError(f"fit failed: {fit.message}")
    ce = 0.0
    for exp in experiments:
        p = softmax_probs(exp, columns, fit.x)
        ce += -float(exp.truth @ np.log(np.maximum(p, 1e-300)))
    return fit.x, ce / total_tickets


def spearman(truth: np.ndarray, score: np.ndarray) -> float:
    if np.all(truth == truth[0]) or np.all(score == score[0]):
        return 0.0
    return float(np.corrcoef(rankdata(truth), rankdata(score))[0, 1])


def evaluate(experiments: list[Experiment], columns: tuple[int, ...], coef: np.ndarray) -> dict[str, float | int]:
    cells = tickets = exact = 0
    abs_error = log_sq = ce = 0.0
    rhos = []
    top_third_truth_mass = []
    top_third_pred_mass = []
    for exp in experiments:
        p = softmax_probs(exp, columns, coef)
        pred, _ = proportional_integer_allocation(exp.residual, p)
        cells += len(exp.truth)
        tickets += exp.residual
        abs_error += float(np.abs(pred - exp.truth).sum())
        log_sq += float(np.square(np.log1p(pred) - np.log1p(exp.truth)).sum())
        exact += int((pred == exp.truth).sum())
        ce += -float(exp.truth @ np.log(np.maximum(p, 1e-300)))
        rhos.append(spearman(exp.truth, p))

        order = np.argsort(-p, kind="stable")
        top = order[: max(1, math.ceil(len(order) / 3))]
        top_third_truth_mass.append(float(exp.truth[top].sum() / exp.residual))
        top_third_pred_mass.append(float(p[top].sum()))

    return {
        "races": len(experiments),
        "cells": cells,
        "mae": abs_error / cells,
        "log_rmse": math.sqrt(log_sq / cells),
        "exact": exact / cells,
        "ce": ce / tickets,
        "median_spearman": statistics.median(rhos),
        "median_top_truth": statistics.median(top_third_truth_mass),
        "median_top_pred": statistics.median(top_third_pred_mass),
    }


def coef_text(columns: tuple[int, ...], coef: np.ndarray) -> str:
    if not columns:
        return "-"
    return ";".join(f"{FEATURE_MODELS[c]}={v:.3f}" for c, v in zip(columns, coef))


def main() -> int:
    data = pathlib.Path("데이터")
    races = load_races(data / "races.jsonl.gz")
    feasible = load_feasible(data / "trifecta_feasible_sets.csv.gz")
    wanted = {rid for rid, info in feasible.items() if int(info["capped_cells"]) > 0}
    grids = load_grids(data, races, wanted)
    cross = load_cross_pool_odds(data, wanted)

    print("# Same-regime pseudo-censoring: all races already contain real 9999.9 cells")
    print("threshold,method,train_races,test_races,train_cells,test_cells,coef,train_ce,test_ce,MAE,log1p_RMSE,exact,median_spearman,median_truth_mass_in_pred_top_third,median_pred_mass_top_third")
    for threshold in THRESHOLDS:
        experiments = []
        for i, rid in enumerate(sorted(wanted), 1):
            exp = build_experiment(races[rid], grids[rid], cross.get(rid, {}), threshold)
            if exp is not None:
                experiments.append(exp)
            if i % 1000 == 0:
                print(f"# u={threshold:.0f} scanned={i}/{len(wanted)} usable={len(experiments)}", flush=True)
        train = [e for e in experiments if e.year <= "2024"]
        test = [e for e in experiments if e.year == "2025"]
        if not train or not test:
            raise ValueError(f"empty train/test at {threshold}")
        for method, columns in METHODS.items():
            coef, train_ce = fit_coefficients(train, columns)
            out = evaluate(test, columns, coef)
            print(
                f"{threshold:.0f},{method},{len(train)},{len(test)},"
                f"{sum(len(e.truth) for e in train)},{out['cells']},{coef_text(columns,coef)},"
                f"{train_ce:.6f},{out['ce']:.6f},{out['mae']:.3f},{out['log_rmse']:.4f},"
                f"{out['exact']:.4%},{out['median_spearman']:.4f},"
                f"{out['median_top_truth']:.4f},{out['median_top_pred']:.4f}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
