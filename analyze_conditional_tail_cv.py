#!/usr/bin/env python3
"""Select a conditional empirical-tail correction using 2022--2024 only.

Design
------
1. Create artificial-cap examples from uncapped 2022--2024 races at the same
   3000/5000/7000/9000 thresholds used elsewhere.
2. For each example, fit a shifted power law using only the cells left visible
   by that artificial cap.  The hidden truth is used only to learn a residual
   tail-shape curve.
3. Choose the conditioning rule by leave-one-year-out cross-validation inside
   2022--2024.  Candidate rules use k-nearest training races in observable
   race/fit characteristics.  2025 is never used for model selection.
4. Lock the best rule, train it on all 2022--2024 examples, then evaluate once
   on the corrected 2025 clean-race and genuinely-capped near-tail tests.

All methods use the same hidden-ticket total and the same cellwise accounting
bounds.  This script is diagnostic and does not overwrite maintained outputs.
"""
from __future__ import annotations

import math
import pathlib
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from analyze_masked_reconstruction import (
    _won,
    bounded_integer_projection,
    load_grids,
    load_races,
    reconstruct_counts,
)
from analyze_power_law_rank_audit import (
    fit_shifted_power,
    fit_training,
    power_clean_rows,
    power_near_rows,
)
from analyze_rank_profile_correction import (
    bounded_weight_allocation_bounds,
    corrected_clean_rows,
    corrected_near_tail_rows,
    hidden_total_interval_bounds,
)
from analyze_rank_profile_imputation import (
    VALIDATION_THRESHOLDS,
    aggregate_validation,
    capped_ids,
    complete_visible_counts,
    in_common_support,
    internal_assignment_scores,
    load_month_grids,
    uncapped_ids,
    validation_row,
)
from kra.feasible import DISPLAY_CAP, capped_ticket_upper


GRID = np.linspace(0.50, 0.995, 100)
FEATURE_SETS = {
    "fit_only": ("alpha", "log_shift"),
    "fit_race": ("alpha", "log_shift", "log_density", "starters"),
}
K_VALUES = (25, 50, 100, 200)


@dataclass
class Example:
    race_id: str
    year: str
    threshold: float
    features: dict[str, float]
    curve: np.ndarray


@dataclass
class Bank:
    feature_names: tuple[str, ...]
    matrix: np.ndarray
    curves: np.ndarray
    center: np.ndarray
    scale: np.ndarray
    global_curve: np.ndarray


def _features(fit: dict[str, float], *, total: int, cells: int, starters: int) -> dict[str, float]:
    return {
        "alpha": float(fit["alpha"]),
        "log_shift": math.log1p(float(fit["shift"])),
        "log_density": math.log(max(total / cells, 1e-12)),
        "starters": float(starters),
    }


def _curve_from_truth(
    truth: np.ndarray,
    visible_count: int,
    fit: dict[str, float],
) -> np.ndarray:
    """Centered log residual curve in ranks hidden by an artificial cap."""
    ordered = np.sort(np.asarray(truth, dtype=float))[::-1]
    ranks = np.arange(1, len(ordered) + 1, dtype=float)
    positions = (ranks - 0.5) / len(ordered)
    fitted_log = float(fit["intercept"]) - float(fit["alpha"]) * np.log(
        ranks + float(fit["shift"])
    )
    keep = (ranks > visible_count) & (ordered > 0) & (positions >= GRID[0])
    if int(keep.sum()) < 2:
        return np.full(len(GRID), np.nan)
    residual = np.log(ordered[keep]) - fitted_log[keep]
    pos = positions[keep]
    curve = np.full(len(GRID), np.nan)
    covered = (GRID >= pos.min()) & (GRID <= pos.max())
    if covered.any():
        curve[covered] = np.interp(GRID[covered], pos, residual)
        first = int(np.flatnonzero(covered)[0])
        curve[covered] -= curve[first]
    return curve


def build_examples(data: pathlib.Path, races, feasible) -> list[Example]:
    ids = uncapped_ids(feasible, years={"2022", "2023", "2024"})
    grids = load_grids(data, races, ids)
    examples: list[Example] = []
    for race_id in sorted(grids):
        values = grids[race_id]
        sales = _won(races[race_id]["sales"]["삼쌍승식"])
        total = sales // 100
        truth, lower, upper = reconstruct_counts(sales, values)
        odds = np.asarray([float(value) for _, value in values])
        starters = int(feasible[race_id]["starters"])
        for threshold in VALIDATION_THRESHOLDS:
            hidden = odds >= float(threshold)
            if not hidden.any() or hidden.all() or np.any(lower[hidden] != upper[hidden]):
                continue
            visible = ~hidden
            cap_upper = capped_ticket_upper(sales, cap=threshold)
            hlo = np.ones(int(hidden.sum()), dtype=np.int64)
            hhi = np.full(int(hidden.sum()), cap_upper, dtype=np.int64)
            try:
                rlo, rhi = hidden_total_interval_bounds(
                    total, lower[visible], upper[visible], hlo, hhi
                )
            except ValueError:
                continue
            hidden_tickets = (rlo + rhi) // 2
            target = np.asarray([0.73 * total / float(value) for _, value in values])
            observed = np.zeros(len(values), dtype=np.int64)
            observed[visible] = bounded_integer_projection(
                target[visible], lower[visible], upper[visible], total - hidden_tickets
            )
            head = np.sort(observed[visible].astype(float))[::-1]
            if len(head) < 4 or np.count_nonzero(head) < 4:
                continue
            try:
                fit = fit_shifted_power(head, np.arange(1, len(head) + 1, dtype=float))
            except ValueError:
                continue
            curve = _curve_from_truth(truth, int(visible.sum()), fit)
            if np.count_nonzero(np.isfinite(curve)) < 2:
                continue
            examples.append(Example(
                race_id=race_id,
                year=str(feasible[race_id]["year"]),
                threshold=float(threshold),
                features=_features(fit, total=total, cells=len(values), starters=starters),
                curve=curve,
            ))
    return examples


def make_bank(examples: list[Example], feature_names: tuple[str, ...]) -> Bank:
    if not examples:
        raise ValueError("empty conditional-correction bank")
    matrix = np.asarray([
        [example.features[name] for name in feature_names] for example in examples
    ], dtype=float)
    center = np.median(matrix, axis=0)
    q25 = np.quantile(matrix, 0.25, axis=0)
    q75 = np.quantile(matrix, 0.75, axis=0)
    scale = np.maximum(q75 - q25, 1e-6)
    curves = np.stack([example.curve for example in examples])
    global_curve = np.nanmedian(curves, axis=0)
    global_curve = np.where(np.isfinite(global_curve), global_curve, 0.0)
    return Bank(feature_names, matrix, curves, center, scale, global_curve)


def conditional_curve(bank: Bank, features: dict[str, float], k: int) -> np.ndarray:
    x = np.asarray([features[name] for name in bank.feature_names], dtype=float)
    standardized = (bank.matrix - bank.center) / bank.scale
    target = (x - bank.center) / bank.scale
    distance = np.square(standardized - target).sum(axis=1)
    take = min(k, len(distance))
    indices = np.argpartition(distance, take - 1)[:take]
    curve = np.nanmedian(bank.curves[indices], axis=0)
    curve = np.where(np.isfinite(curve), curve, bank.global_curve)
    # Shape-only correction: make factor 1 at the first grid point.
    curve = curve - curve[0]
    return curve


def factor(positions: np.ndarray, curve: np.ndarray) -> np.ndarray:
    log_factor = np.interp(
        np.asarray(positions, dtype=float), GRID, curve,
        left=float(curve[0]), right=float(curve[-1]),
    )
    return np.exp(log_factor)


def conditional_scores(
    observed: np.ndarray,
    visible: np.ndarray,
    hidden: np.ndarray,
    combos: list[tuple[int, int, int]],
    horses: list[int],
    *,
    total: int,
    starters: int,
    bank: Bank,
    k: int,
) -> tuple[np.ndarray, dict[str, float]]:
    head = np.sort(observed[visible].astype(float))[::-1]
    fit = fit_shifted_power(head, np.arange(1, len(head) + 1, dtype=float))
    feats = _features(fit, total=total, cells=len(observed), starters=starters)
    curve = conditional_curve(bank, feats, k)
    ranks = np.arange(len(head) + 1, len(observed) + 1, dtype=float)
    positions = (ranks - 0.5) / len(observed)
    scores = np.power(ranks + fit["shift"], -fit["alpha"]) * factor(positions, curve)
    assignment = internal_assignment_scores(combos, observed, visible, hidden, horses)
    order = np.argsort(-assignment, kind="stable")
    cell_scores = np.empty(len(scores), dtype=float)
    cell_scores[order] = scores
    return cell_scores, fit


def cv_score_examples(
    data: pathlib.Path,
    races,
    feasible,
    examples: list[Example],
    feature_names: tuple[str, ...],
    k: int,
) -> tuple[float, dict[float, float]]:
    """Leave-one-year-out clean virtual-cap score; equal weight across thresholds."""
    by_threshold: dict[float, list[tuple[int, int]]] = defaultdict(list)
    grid_cache: dict[str, list] = {}
    all_ids = {example.race_id for example in examples}
    loaded = load_grids(data, races, all_ids)
    grid_cache.update(loaded)

    for held_year in ("2022", "2023", "2024"):
        training = [e for e in examples if e.year != held_year]
        banks = {
            threshold: make_bank(
                [e for e in training if e.threshold == threshold], feature_names
            )
            for threshold in VALIDATION_THRESHOLDS
            if any(e.threshold == threshold for e in training)
        }
        validation = [e for e in examples if e.year == held_year]
        for example in validation:
            if example.threshold not in banks:
                continue
            race_id = example.race_id
            values = grid_cache[race_id]
            sales = _won(races[race_id]["sales"]["삼쌍승식"])
            total = sales // 100
            truth, lower, upper = reconstruct_counts(sales, values)
            odds = np.asarray([float(value) for _, value in values])
            hidden = odds >= example.threshold
            if not hidden.any() or hidden.all():
                continue
            visible = ~hidden
            cap_upper = capped_ticket_upper(sales, cap=example.threshold)
            hlo = np.ones(int(hidden.sum()), dtype=np.int64)
            hhi = np.full(int(hidden.sum()), cap_upper, dtype=np.int64)
            rlo, rhi = hidden_total_interval_bounds(
                total, lower[visible], upper[visible], hlo, hhi
            )
            hidden_tickets = (rlo + rhi) // 2
            target = np.asarray([0.73 * total / float(value) for _, value in values])
            observed = np.zeros(len(values), dtype=np.int64)
            observed[visible] = bounded_integer_projection(
                target[visible], lower[visible], upper[visible], total - hidden_tickets
            )
            combos = [combo for combo, _ in values]
            horses = sorted(set(races[race_id]["horses"]) - set(races[race_id].get("scratched") or []))
            scores, _ = conditional_scores(
                observed, visible, hidden, combos, horses,
                total=total, starters=int(feasible[race_id]["starters"]),
                bank=banks[example.threshold], k=k,
            )
            prediction = bounded_weight_allocation_bounds(
                hidden_tickets, scores, hlo, hhi
            )
            error = int(np.abs(prediction - truth[hidden]).sum())
            by_threshold[example.threshold].append((error, int(hidden.sum())))

    ratios = []
    threshold_mae = {}
    # The absolute CV criterion is equal-threshold average MAE normalized by
    # the threshold's unconditional shifted-power baseline, preventing 3000
    # from dominating simply because it hides many more cells.
    shifted_baseline = cv_shifted_baseline(data, races, feasible, examples, grid_cache)
    for threshold in VALIDATION_THRESHOLDS:
        values = by_threshold.get(float(threshold), [])
        if not values:
            continue
        mae = sum(error for error, _ in values) / sum(cells for _, cells in values)
        threshold_mae[float(threshold)] = mae
        ratios.append(mae / shifted_baseline[float(threshold)])
    return float(np.mean(ratios)), threshold_mae


def cv_shifted_baseline(data, races, feasible, examples, grids) -> dict[float, float]:
    by_threshold: dict[float, list[tuple[int, int]]] = defaultdict(list)
    seen = set()
    for example in examples:
        key = (example.race_id, example.threshold)
        if key in seen:
            continue
        seen.add(key)
        race_id = example.race_id
        values = grids[race_id]
        sales = _won(races[race_id]["sales"]["삼쌍승식"])
        total = sales // 100
        truth, lower, upper = reconstruct_counts(sales, values)
        odds = np.asarray([float(value) for _, value in values])
        hidden = odds >= example.threshold
        visible = ~hidden
        cap_upper = capped_ticket_upper(sales, cap=example.threshold)
        hlo = np.ones(int(hidden.sum()), dtype=np.int64)
        hhi = np.full(int(hidden.sum()), cap_upper, dtype=np.int64)
        rlo, rhi = hidden_total_interval_bounds(total, lower[visible], upper[visible], hlo, hhi)
        hidden_tickets = (rlo + rhi) // 2
        target = np.asarray([0.73 * total / float(value) for _, value in values])
        observed = np.zeros(len(values), dtype=np.int64)
        observed[visible] = bounded_integer_projection(
            target[visible], lower[visible], upper[visible], total - hidden_tickets
        )
        head = np.sort(observed[visible].astype(float))[::-1]
        fit = fit_shifted_power(head, np.arange(1, len(head) + 1, dtype=float))
        ranks = np.arange(len(head) + 1, len(values) + 1, dtype=float)
        scores_rank = np.power(ranks + fit["shift"], -fit["alpha"])
        combos = [combo for combo, _ in values]
        horses = sorted(set(races[race_id]["horses"]) - set(races[race_id].get("scratched") or []))
        assignment = internal_assignment_scores(combos, observed, visible, hidden, horses)
        order = np.argsort(-assignment, kind="stable")
        scores = np.empty(len(scores_rank), dtype=float)
        scores[order] = scores_rank
        prediction = bounded_weight_allocation_bounds(hidden_tickets, scores, hlo, hhi)
        by_threshold[example.threshold].append((
            int(np.abs(prediction - truth[hidden]).sum()), int(hidden.sum())
        ))
    return {
        threshold: sum(e for e, _ in rows) / sum(n for _, n in rows)
        for threshold, rows in by_threshold.items()
    }


def final_clean_rows(races, feasible, bounds, data, banks, feature_names, k):
    rows = []
    ids = uncapped_ids(feasible, years={"2025"})
    grids = load_grids(data, races, ids)
    for race_id in sorted(grids):
        values = grids[race_id]
        sales = _won(races[race_id]["sales"]["삼쌍승식"])
        total = sales // 100
        truth, lower, upper = reconstruct_counts(sales, values)
        odds = np.asarray([float(value) for _, value in values])
        combos = [combo for combo, _ in values]
        horses = sorted(set(races[race_id]["horses"]) - set(races[race_id].get("scratched") or []))
        common = in_common_support(feasible[race_id], bounds)
        for threshold in VALIDATION_THRESHOLDS:
            hidden = odds >= float(threshold)
            if not hidden.any() or hidden.all() or np.any(lower[hidden] != upper[hidden]):
                continue
            visible = ~hidden
            cap_upper = capped_ticket_upper(sales, cap=threshold)
            hlo = np.ones(int(hidden.sum()), dtype=np.int64)
            hhi = np.full(int(hidden.sum()), cap_upper, dtype=np.int64)
            rlo, rhi = hidden_total_interval_bounds(total, lower[visible], upper[visible], hlo, hhi)
            hidden_tickets = (rlo + rhi) // 2
            target = np.asarray([0.73 * total / float(value) for _, value in values])
            observed = np.zeros(len(values), dtype=np.int64)
            observed[visible] = bounded_integer_projection(
                target[visible], lower[visible], upper[visible], total - hidden_tickets
            )
            scores, fit = conditional_scores(
                observed, visible, hidden, combos, horses,
                total=total, starters=int(feasible[race_id]["starters"]),
                bank=banks[float(threshold)], k=k,
            )
            prediction = bounded_weight_allocation_bounds(hidden_tickets, scores, hlo, hhi)
            rows.append(validation_row(
                sample="clean_2025", race_id=race_id, year="2025",
                threshold=threshold, model="conditional_tail_cv",
                common_support=common, hidden_cells=int(hidden.sum()),
                assessed_truth=truth[hidden], assessed_prediction=prediction,
                hidden_tickets=hidden_tickets, rank_truth=truth[hidden],
                rank_prediction=prediction,
                profile_class=f"{','.join(feature_names)};k={k};alpha={fit['alpha']:.4f};shift={fit['shift']:.4f}",
            ))
    return rows


def final_near_rows(races, feasible, bounds, data, banks, feature_names, k):
    rows = []
    target_ids = {
        race_id for race_id in capped_ids(feasible)
        if str(feasible[race_id]["year"]) == "2025"
    }
    paths = sorted((data / "cells" / "page_key=3Both").glob("2025*.csv.gz"))
    for path in paths:
        month_ids = {race_id for race_id in target_ids if race_id[:7] == path.name[:7]}
        grids = load_month_grids(path, races, month_ids)
        for race_id in sorted(grids):
            values = grids[race_id]
            info = feasible[race_id]
            combos = [combo for combo, _ in values]
            sales = _won(races[race_id]["sales"]["삼쌍승식"])
            total = sales // 100
            horses = sorted(set(races[race_id]["horses"]) - set(races[race_id].get("scratched") or []))
            _, _, capped, lower, upper = complete_visible_counts(
                sales, values, int(info["residual_mid"])
            )
            common = in_common_support(info, bounds)
            for threshold in VALIDATION_THRESHOLDS:
                newly_hidden = np.asarray([
                    value != DISPLAY_CAP and value >= threshold for _, value in values
                ])
                if not newly_hidden.any() or np.any(lower[newly_hidden] != upper[newly_hidden]):
                    continue
                hidden = capped | newly_hidden
                visible = ~hidden
                hidden_idx = np.flatnonzero(hidden)
                virtual_upper = capped_ticket_upper(sales, cap=threshold)
                actual_upper = int(info["cap_upper"])
                hlo = np.asarray([0 if capped[i] else actual_upper + 1 for i in hidden_idx], dtype=np.int64)
                hhi = np.asarray([actual_upper if capped[i] else virtual_upper for i in hidden_idx], dtype=np.int64)
                rlo, rhi = hidden_total_interval_bounds(total, lower[visible], upper[visible], hlo, hhi)
                hidden_tickets = (rlo + rhi) // 2
                target = np.asarray([
                    0.0 if value == DISPLAY_CAP else 0.73 * total / float(value)
                    for _, value in values
                ])
                observed = np.zeros(len(values), dtype=np.int64)
                observed[visible] = bounded_integer_projection(
                    target[visible], lower[visible], upper[visible], total - hidden_tickets
                )
                scores, fit = conditional_scores(
                    observed, visible, hidden, combos, horses,
                    total=total, starters=int(info["starters"]),
                    bank=banks[float(threshold)], k=k,
                )
                prediction = bounded_weight_allocation_bounds(hidden_tickets, scores, hlo, hhi)
                newly_local = np.flatnonzero(newly_hidden[hidden])
                assessed = prediction[newly_local]
                truth = lower[newly_hidden]
                rows.append(validation_row(
                    sample="capped_near_tail_2025", race_id=race_id, year="2025",
                    threshold=threshold, model="conditional_tail_cv",
                    common_support=common, hidden_cells=int(hidden.sum()),
                    assessed_truth=truth, assessed_prediction=assessed,
                    hidden_tickets=hidden_tickets, rank_truth=truth,
                    rank_prediction=assessed,
                    profile_class=f"{','.join(feature_names)};k={k};alpha={fit['alpha']:.4f};shift={fit['shift']:.4f}",
                ))
    return rows


def report(cv_rows, selected, final_rows):
    feature_key, k, score, threshold_mae = selected
    lines = [
        "# Conditional empirical-tail correction: pre-2025 model selection",
        "",
        "2025 is held out completely during model selection. Candidate rules are chosen by leave-one-year-out cross-validation within 2022--2024.",
        "",
        "## Cross-validation candidates",
        "",
        "Selection score is the equal-threshold mean of candidate MAE / shifted-power MAE. Lower is better; below 1 improves on shifted power.",
        "",
        "| features | k | selection score | 3000 MAE | 5000 MAE | 7000 MAE | 9000 MAE |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in sorted(cv_rows, key=lambda r: r["score"]):
        lines.append(
            f"| {row['feature_key']} | {row['k']} | {row['score']:.5f} | "
            + " | ".join(f"{row['threshold_mae'].get(float(t), float('nan')):.3f}" for t in VALIDATION_THRESHOLDS)
            + " |"
        )
    lines.extend([
        "",
        f"Locked rule before reading 2025: features={feature_key}, k={k}, CV score={score:.5f}.",
        "",
        "## Final untouched 2025 test",
        "",
        "| sample | cap | support | model | races | cells | MAE | rank MAE |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ])
    agg = aggregate_validation(final_rows)
    for row in sorted(agg, key=lambda r: (
        str(r["sample"]), float(r["threshold"]), str(r["common_support"]), str(r["model"])
    )):
        if row["sample"] not in {"clean_2025", "capped_near_tail_2025"}:
            continue
        rank_mae = float(row["rank_mae"]) if row["rank_mae"] is not None else float("nan")
        lines.append(
            f"| {row['sample']} | {row['threshold']} | {'in' if row['common_support']=='1' else 'out'} | {row['model']} | "
            f"{int(row['races'])} | {int(row['cells'])} | {float(row['mae']):.3f} | {rank_mae:.3f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    data = pathlib.Path("데이터")
    races, feasible, mixture, bounds, _ = fit_training(data)
    examples = build_examples(data, races, feasible)
    if any(example.year == "2025" for example in examples):
        raise AssertionError("2025 leaked into cross-validation examples")

    cv_rows = []
    for feature_key, names in FEATURE_SETS.items():
        for k in K_VALUES:
            score, threshold_mae = cv_score_examples(
                data, races, feasible, examples, names, k
            )
            cv_rows.append({
                "feature_key": feature_key,
                "feature_names": names,
                "k": k,
                "score": score,
                "threshold_mae": threshold_mae,
            })
            print(f"CV {feature_key} k={k}: score={score:.5f}", flush=True)
    best = min(cv_rows, key=lambda row: (row["score"], row["k"], row["feature_key"]))
    feature_names = tuple(best["feature_names"])
    k = int(best["k"])

    banks = {
        float(threshold): make_bank(
            [example for example in examples if example.threshold == float(threshold)],
            feature_names,
        )
        for threshold in VALIDATION_THRESHOLDS
    }

    # Comparator rows are recomputed in the same run and with the same accounting bounds.
    baseline_clean = corrected_clean_rows(races, feasible, mixture, bounds, data)
    baseline_near, _ = corrected_near_tail_rows(races, feasible, mixture, bounds, data)
    shifted_clean = power_clean_rows(races, feasible, bounds, data)
    shifted_near = power_near_rows(races, feasible, bounds, data)
    conditional_clean = final_clean_rows(races, feasible, bounds, data, banks, feature_names, k)
    conditional_near = final_near_rows(races, feasible, bounds, data, banks, feature_names, k)
    rows = baseline_clean + baseline_near + shifted_clean + shifted_near + conditional_clean + conditional_near

    selected = (
        str(best["feature_key"]), k, float(best["score"]), best["threshold_mae"]
    )
    text = report(cv_rows, selected, rows)
    print(text)
    pathlib.Path("findings/conditional_tail_cv.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
