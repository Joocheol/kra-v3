#!/usr/bin/env python3
"""Out-of-time joint reconstruction of artificially censored trifecta tails.

This extends the one-score masked experiments by fitting a small log-linear
ensemble of same-pool and cross-pool signals.  Coefficients are learned from
2022--2024 ticket allocations only; realised finishing orders are never used
for fitting.  Performance is then measured on 2025, with special attention to
whether the model can rank cells *within* the hidden longshot tail, which is
needed before a fine-grained FLB curve can be trusted.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import statistics
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from scipy.stats import rankdata

from analyze_masked_reconstruction import (
    MODELS,
    THRESHOLDS,
    ModelUnavailable,
    _won,
    load_cross_pool_odds,
    load_grids,
    load_races,
    model_scores,
    primary_race_ids,
    proportional_integer_allocation,
    reconstruct_counts,
)

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


@dataclass
class Experiment:
    race_id: str
    date: str
    year: str
    features: np.ndarray
    truth: np.ndarray
    residual: int
    total: int
    outcome_masked_index: int | None


def _valid_outcome(race: dict, combos: list[tuple[int, int, int]], masked: np.ndarray) -> int | None:
    arrival = race.get("arrival") or []
    if len(arrival) < 3:
        return None
    outcome = tuple(arrival[:3])
    if len(set(outcome)) != 3:
        return None
    try:
        global_index = combos.index(outcome)
    except ValueError:
        return None
    if not masked[global_index]:
        return None
    local = np.flatnonzero(masked)
    where = np.flatnonzero(local == global_index)
    return int(where[0]) if len(where) == 1 else None


def build_experiment(
    race: dict,
    values: list[tuple[tuple[int, int, int], Decimal]],
    cross_pool: dict[str, dict[tuple[int, ...], float]],
    threshold: float,
) -> Experiment | None:
    sales = _won(race["sales"]["삼쌍승식"])
    counts, lower, upper = reconstruct_counts(sales, values)
    combos = [combo for combo, _ in values]
    odds = np.asarray([float(value) for _, value in values])
    masked = odds >= threshold
    if not masked.any() or masked.all():
        return None
    if np.any(lower[masked] != upper[masked]):
        return None
    visible = ~masked
    active = sorted(set(race["horses"]) - set(race.get("scratched") or []))
    columns = []
    for model in FEATURE_MODELS:
        try:
            score = model_scores(
                model, combos, counts, visible, masked, active,
                cross_pool=cross_pool,
            )
        except ModelUnavailable:
            return None
        if np.any(score <= 0) or not np.isfinite(score).all():
            return None
        log_score = np.log(score)
        # Race-specific multiplicative constants have no role in a within-race
        # softmax; centring improves numerical conditioning without changing it.
        columns.append(log_score - log_score.mean())
    features = np.column_stack(columns)
    truth = counts[masked].astype(float)
    residual = int(truth.sum())
    if residual <= 0:
        return None
    total = sales // 100
    return Experiment(
        race_id=race["race_id"],
        date=race["date"],
        year=race["date"][:4],
        features=features,
        truth=truth,
        residual=residual,
        total=total,
        outcome_masked_index=_valid_outcome(race, combos, masked),
    )


def softmax_probs(exp: Experiment, columns: tuple[int, ...], coef: np.ndarray) -> np.ndarray:
    if not columns:
        return np.full(len(exp.truth), 1.0 / len(exp.truth))
    x = exp.features[:, columns]
    logits = x @ coef
    return np.exp(logits - logsumexp(logits))


def fit_coefficients(experiments: list[Experiment], columns: tuple[int, ...]) -> tuple[np.ndarray, float]:
    if not columns:
        ce = sum(exp.residual * math.log(len(exp.truth)) for exp in experiments) / sum(exp.residual for exp in experiments)
        return np.empty(0), ce
    total_tickets = sum(exp.residual for exp in experiments)

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

    start = np.full(len(columns), 0.10)
    fitted = minimize(
        lambda t: objective(t)[0], start,
        jac=lambda t: objective(t)[1],
        method="L-BFGS-B",
        bounds=[(0.0, MAX_COEF)] * len(columns),
        options={"maxiter": 300, "ftol": 1e-12, "gtol": 1e-8},
    )
    if not fitted.success:
        raise RuntimeError(f"joint fit failed: {fitted.message}")
    ce = 0.0
    for exp in experiments:
        p = softmax_probs(exp, columns, fitted.x)
        ce += -float(exp.truth @ np.log(np.maximum(p, 1e-300)))
    return fitted.x, ce / total_tickets


def spearman_truth_score(truth: np.ndarray, score: np.ndarray) -> float:
    if np.all(score == score[0]) or np.all(truth == truth[0]):
        return 0.0
    a = rankdata(truth)
    b = rankdata(score)
    return float(np.corrcoef(a, b)[0, 1])


def rank_thirds(probabilities: np.ndarray) -> np.ndarray:
    order = np.argsort(-probabilities, kind="stable")
    groups = np.empty(len(order), dtype=int)
    for group, indexes in enumerate(np.array_split(order, 3)):
        groups[indexes] = group
    return groups


def evaluate(
    experiments: list[Experiment], columns: tuple[int, ...], coef: np.ndarray,
) -> dict[str, object]:
    cells = tickets = exact = 0
    abs_error = log_sq = ce = 0.0
    rhos = []
    winner_log_ratios = []
    restored_o = np.zeros(3)
    restored_e = np.zeros(3)
    truth_o = np.zeros(3)
    truth_e = np.zeros(3)
    masked_winners = 0

    for exp in experiments:
        probs = softmax_probs(exp, columns, coef)
        predicted, _ = proportional_integer_allocation(exp.residual, probs)
        cells += len(exp.truth)
        tickets += exp.residual
        abs_error += float(np.abs(predicted - exp.truth).sum())
        log_sq += float(np.square(np.log1p(predicted) - np.log1p(exp.truth)).sum())
        exact += int((predicted == exp.truth).sum())
        ce += -float(exp.truth @ np.log(np.maximum(probs, 1e-300)))
        rhos.append(spearman_truth_score(exp.truth, probs))

        restored_share = exp.residual / exp.total * probs
        truth_share = exp.truth / exp.total
        restored_group = rank_thirds(probs)
        truth_group = rank_thirds(exp.truth)
        for group in range(3):
            restored_e[group] += float(restored_share[restored_group == group].sum())
            truth_e[group] += float(truth_share[truth_group == group].sum())
        if exp.outcome_masked_index is not None:
            idx = exp.outcome_masked_index
            masked_winners += 1
            restored_o[restored_group[idx]] += 1
            truth_o[truth_group[idx]] += 1
            true_p = truth_share[idx]
            pred_p = restored_share[idx]
            if true_p > 0 and pred_p > 0:
                winner_log_ratios.append(math.log(pred_p / true_p))

    return {
        "races": len(experiments),
        "cells": cells,
        "mae": abs_error / cells,
        "log_rmse": math.sqrt(log_sq / cells),
        "exact": exact / cells,
        "ce": ce / tickets,
        "median_spearman": statistics.median(rhos),
        "masked_winners": masked_winners,
        "winner_geo_ratio": math.exp(statistics.median(winner_log_ratios)) if winner_log_ratios else math.nan,
        "restored_oe": [restored_o[i] / restored_e[i] if restored_e[i] else math.nan for i in range(3)],
        "truth_oe": [truth_o[i] / truth_e[i] if truth_e[i] else math.nan for i in range(3)],
        "restored_o": restored_o,
        "truth_o": truth_o,
    }


def coef_text(columns: tuple[int, ...], coef: np.ndarray) -> str:
    if not columns:
        return "-"
    return ";".join(f"{FEATURE_MODELS[c]}={v:.3f}" for c, v in zip(columns, coef))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    args = parser.parse_args()

    races = load_races(args.data / "races.jsonl.gz")
    wanted = primary_race_ids(args.data / "trifecta_feasible_sets.csv.gz")
    grids = load_grids(args.data, races, wanted)
    cross_pool = load_cross_pool_odds(args.data, wanted)

    print("threshold,method,train_races,test_races,coef,train_ce,test_ce,MAE,log1p_RMSE,exact,median_spearman,masked_winners,winner_pred_over_true_geo,truth_OE_top_mid_bottom,restored_OE_top_mid_bottom,truth_hits_top_mid_bottom,restored_hits_top_mid_bottom")
    for threshold_decimal in THRESHOLDS:
        threshold = float(threshold_decimal)
        experiments = []
        for index, race_id in enumerate(sorted(wanted), 1):
            exp = build_experiment(
                races[race_id], grids[race_id], cross_pool.get(race_id, {}), threshold
            )
            if exp is not None:
                experiments.append(exp)
            if index % 500 == 0:
                print(f"# threshold {threshold:.0f}: scanned {index}/{len(wanted)} usable={len(experiments)}", flush=True)
        train = [exp for exp in experiments if exp.year <= "2024"]
        test = [exp for exp in experiments if exp.year == "2025"]
        if not train or not test:
            raise ValueError(f"empty train/test at threshold {threshold}")
        for method, columns in METHODS.items():
            coef, train_ce = fit_coefficients(train, columns)
            result = evaluate(test, columns, coef)
            truth_oe = "/".join(f"{x:.3f}" for x in result["truth_oe"])
            restored_oe = "/".join(f"{x:.3f}" for x in result["restored_oe"])
            truth_hits = "/".join(str(int(x)) for x in result["truth_o"])
            restored_hits = "/".join(str(int(x)) for x in result["restored_o"])
            print(
                f"{threshold:.0f},{method},{len(train)},{len(test)},{coef_text(columns, coef)},"
                f"{train_ce:.5f},{result['ce']:.5f},{result['mae']:.3f},{result['log_rmse']:.4f},"
                f"{result['exact']:.4%},{result['median_spearman']:.4f},{result['masked_winners']},"
                f"{result['winner_geo_ratio']:.4f},{truth_oe},{restored_oe},{truth_hits},{restored_hits}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
