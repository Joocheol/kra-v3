#!/usr/bin/env python3
"""Recompute rank-profile validation with symmetric lower/upper information.

This audit responds to the Claude review of PR #5.  Artificially hidden cells
receive every lower bound implied by the masking design, and both the rank
profile model and the uniform baseline receive exactly the same cellwise
bounds.  Existing committed artifacts are read only; this script prints a
side-by-side audit and does not overwrite them.
"""
from __future__ import annotations

import csv
import gzip
import math
import pathlib
from collections import defaultdict
from decimal import Decimal

import numpy as np

from analyze_masked_reconstruction import (
    _won,
    bounded_integer_projection,
    load_grids,
    load_races,
    reconstruct_counts,
)
from analyze_rank_profile_imputation import (
    VALIDATION_THRESHOLDS,
    aggregate_validation,
    capped_ids,
    complete_visible_counts,
    in_common_support,
    internal_assignment_scores,
    load_feasible,
    load_month_grids,
    support_bounds,
    uncapped_ids,
    validation_row,
)
from kra.feasible import DISPLAY_CAP, capped_ticket_upper
from kra.rank_profile import (
    CLASS_NAMES,
    RankProfileMixture,
    fit_rank_profile_mixture,
    partial_class_probabilities,
    rank_profile,
    tail_rank_scores,
)


def hidden_total_interval_bounds(
    total: int,
    visible_lower: np.ndarray,
    visible_upper: np.ndarray,
    hidden_lower: np.ndarray,
    hidden_upper: np.ndarray,
) -> tuple[int, int]:
    """Feasible hidden total using the same lower/upper information on both sides."""
    vlo = np.asarray(visible_lower, dtype=np.int64)
    vhi = np.asarray(visible_upper, dtype=np.int64)
    hlo = np.asarray(hidden_lower, dtype=np.int64)
    hhi = np.asarray(hidden_upper, dtype=np.int64)
    if (
        total < 0 or vlo.ndim != 1 or vhi.ndim != 1 or hlo.ndim != 1 or hhi.ndim != 1
        or vlo.shape != vhi.shape or hlo.shape != hhi.shape or len(hlo) == 0
        or np.any(vlo < 0) or np.any(vlo > vhi)
        or np.any(hlo < 0) or np.any(hlo > hhi)
    ):
        raise ValueError("invalid ticket bounds")
    lo = max(int(hlo.sum()), total - int(vhi.sum()))
    hi = min(int(hhi.sum()), total - int(vlo.sum()))
    if lo > hi:
        raise ValueError("ticket bounds are infeasible")
    return lo, hi


def bounded_weight_allocation_bounds(
    total: int,
    scores: np.ndarray,
    lower: int | np.ndarray,
    upper: int | np.ndarray,
) -> np.ndarray:
    """Integer water-filling allocation under cell-specific lower and upper bounds."""
    weights = np.asarray(scores, dtype=float)
    lowers = np.broadcast_to(np.asarray(lower, dtype=np.int64), weights.shape).copy()
    uppers = np.broadcast_to(np.asarray(upper, dtype=np.int64), weights.shape).copy()
    if (
        weights.ndim != 1 or len(weights) == 0 or total < 0
        or np.any(~np.isfinite(weights)) or np.any(weights < 0)
        or np.any(lowers < 0) or np.any(lowers > uppers)
        or total < int(lowers.sum()) or total > int(uppers.sum())
    ):
        raise ValueError("invalid bounded allocation")
    if total == int(lowers.sum()):
        return lowers
    if weights.sum() <= 0:
        weights = np.ones(len(weights), dtype=float)
    else:
        weights = np.maximum(weights, 1e-12)
    low = 0.0
    high = max(1.0, total / max(weights.min(), 1e-12))
    while np.clip(high * weights, lowers, uppers).sum() < total:
        high *= 2.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if np.clip(middle * weights, lowers, uppers).sum() < total:
            low = middle
        else:
            high = middle
    continuous = np.clip(((low + high) / 2.0) * weights, lowers, uppers)
    result = np.floor(continuous + 1e-12).astype(np.int64)
    remainder = total - int(result.sum())
    if remainder < 0:
        raise AssertionError("integer allocation overshot total")
    if remainder:
        eligible = np.flatnonzero(result < uppers)
        fractions = np.round(continuous[eligible] - result[eligible], 12)
        order = eligible[np.argsort(-fractions, kind="stable")]
        if remainder > len(order):
            raise AssertionError("allocation remainder exceeds eligible cells")
        result[order[:remainder]] += 1
    if (
        int(result.sum()) != total or np.any(result < lowers) or np.any(result > uppers)
    ):
        raise AssertionError("bounded allocation failed")
    return result


def predict_hidden_bounds(
    mixture: RankProfileMixture,
    counts: np.ndarray,
    visible: np.ndarray,
    hidden: np.ndarray,
    combos: list[tuple[int, int, int]],
    horses: list[int],
    *,
    total_tickets: int,
    hidden_tickets: int,
    lower: np.ndarray,
    upper: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int]:
    probabilities, distances = partial_class_probabilities(
        counts[visible], total_cells=len(counts), total_tickets=total_tickets,
        mixture=mixture,
    )
    chosen = int(np.argmin(distances))
    rank_scores = tail_rank_scores(
        mixture, chosen, total_cells=len(counts), visible_cells=int(visible.sum())
    )
    assignment = internal_assignment_scores(combos, counts, visible, hidden, horses)
    assignment_order = np.argsort(-assignment, kind="stable")
    cell_scores = np.empty(len(rank_scores), dtype=float)
    cell_scores[assignment_order] = rank_scores
    assigned = bounded_weight_allocation_bounds(
        hidden_tickets, cell_scores, lower, upper
    )
    return assigned, probabilities, chosen


def read_old_rows(path: pathlib.Path) -> list[dict[str, object]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def fit_mixture(data: pathlib.Path):
    races = load_races(data / "races.jsonl.gz")
    feasible = load_feasible(data / "trifecta_feasible_sets.csv.gz")
    train_ids = uncapped_ids(feasible, years={"2022", "2023", "2024"})
    training_grids = load_grids(data, races, train_ids)
    profiles, metadata = [], []
    for race_id in sorted(train_ids):
        sales = _won(races[race_id]["sales"]["삼쌍승식"])
        counts, _, _ = reconstruct_counts(sales, training_grids[race_id])
        profiles.append(rank_profile(counts))
        info = feasible[race_id]
        metadata.append({
            "race_id": race_id,
            "starters": int(info["starters"]),
            "density": int(info["total_tickets"]) / int(info["expected_combinations"]),
        })
    mixture = fit_rank_profile_mixture(np.stack(profiles))
    bounds, _ = support_bounds(metadata, mixture.labels)
    return races, feasible, mixture, bounds


def corrected_clean_rows(races, feasible, mixture, bounds, data: pathlib.Path):
    rows: list[dict[str, object]] = []
    test_ids = uncapped_ids(feasible, years={"2025"})
    grids = load_grids(data, races, test_ids)
    for race_id in sorted(grids):
        race = races[race_id]
        values = grids[race_id]
        sales = _won(race["sales"]["삼쌍승식"])
        total = sales // 100
        truth, lower, upper = reconstruct_counts(sales, values)
        odds = np.asarray([float(value) for _, value in values])
        combos = [combo for combo, _ in values]
        horses = sorted(set(race["horses"]) - set(race.get("scratched") or []))
        common = in_common_support(feasible[race_id], bounds)
        for threshold in VALIDATION_THRESHOLDS:
            hidden = odds >= float(threshold)
            if not hidden.any() or hidden.all() or np.any(lower[hidden] != upper[hidden]):
                continue
            visible = ~hidden
            cap_upper = capped_ticket_upper(sales, cap=threshold)
            hidden_lower = np.ones(int(hidden.sum()), dtype=np.int64)
            hidden_upper = np.full(int(hidden.sum()), cap_upper, dtype=np.int64)
            residual_lo, residual_hi = hidden_total_interval_bounds(
                total, lower[visible], upper[visible], hidden_lower, hidden_upper
            )
            hidden_tickets = (residual_lo + residual_hi) // 2
            target = np.asarray([0.73 * total / float(value) for _, value in values])
            observed = np.zeros(len(values), dtype=np.int64)
            observed[visible] = bounded_integer_projection(
                target[visible], lower[visible], upper[visible], total - hidden_tickets
            )
            predicted, probabilities, chosen = predict_hidden_bounds(
                mixture, observed, visible, hidden, combos, horses,
                total_tickets=total, hidden_tickets=hidden_tickets,
                lower=hidden_lower, upper=hidden_upper,
            )
            uniform = bounded_weight_allocation_bounds(
                hidden_tickets, np.ones(int(hidden.sum())), hidden_lower, hidden_upper
            )
            for model, prediction in (("rank_profile", predicted), ("uniform", uniform)):
                rows.append(validation_row(
                    sample="clean_2025", race_id=race_id, year="2025",
                    threshold=threshold, model=model, common_support=common,
                    hidden_cells=int(hidden.sum()), assessed_truth=truth[hidden],
                    assessed_prediction=prediction, hidden_tickets=hidden_tickets,
                    rank_truth=truth[hidden], rank_prediction=prediction,
                    profile_class=CLASS_NAMES[chosen] if model == "rank_profile" else "",
                ))
    return rows


def corrected_near_tail_rows(races, feasible, mixture, bounds, data: pathlib.Path):
    rows: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    target_ids = {
        race_id for race_id in capped_ids(feasible)
        if str(feasible[race_id]["year"]) == "2025"
    }
    paths = sorted((data / "cells" / "page_key=3Both").glob("2025*.csv.gz"))
    for path in paths:
        month_ids = {race_id for race_id in target_ids if race_id[:7] == path.name[:7]}
        grids = load_month_grids(path, races, month_ids)
        for race_id in sorted(grids):
            race = races[race_id]
            info = feasible[race_id]
            values = grids[race_id]
            combos = [combo for combo, _ in values]
            sales = _won(race["sales"]["삼쌍승식"])
            total = sales // 100
            horses = sorted(set(race["horses"]) - set(race.get("scratched") or []))
            _, visible, capped, lower, upper = complete_visible_counts(
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
                visible_after = ~hidden
                hidden_indices = np.flatnonzero(hidden)
                virtual_upper = capped_ticket_upper(sales, cap=threshold)
                actual_cap_upper = int(info["cap_upper"])
                hidden_lower = np.asarray([
                    0 if capped[index] else actual_cap_upper + 1
                    for index in hidden_indices
                ], dtype=np.int64)
                hidden_upper = np.asarray([
                    actual_cap_upper if capped[index] else virtual_upper
                    for index in hidden_indices
                ], dtype=np.int64)
                residual_lo, residual_hi = hidden_total_interval_bounds(
                    total,
                    lower[visible_after], upper[visible_after],
                    hidden_lower, hidden_upper,
                )
                hidden_tickets = (residual_lo + residual_hi) // 2
                target = np.asarray([
                    0.0 if value == DISPLAY_CAP else 0.73 * total / float(value)
                    for _, value in values
                ])
                base = np.zeros(len(values), dtype=np.int64)
                base[visible_after] = bounded_integer_projection(
                    target[visible_after], lower[visible_after], upper[visible_after],
                    total - hidden_tickets,
                )
                predicted, probabilities, chosen = predict_hidden_bounds(
                    mixture, base, visible_after, hidden, combos, horses,
                    total_tickets=total, hidden_tickets=hidden_tickets,
                    lower=hidden_lower, upper=hidden_upper,
                )
                uniform = bounded_weight_allocation_bounds(
                    hidden_tickets, np.ones(int(hidden.sum())), hidden_lower, hidden_upper
                )
                newly_local = np.flatnonzero(newly_hidden[hidden])
                truth = lower[newly_hidden]
                for model, prediction in (("rank_profile", predicted), ("uniform", uniform)):
                    assessed = prediction[newly_local]
                    rows.append(validation_row(
                        sample="capped_near_tail_2025", race_id=race_id,
                        year="2025", threshold=threshold, model=model,
                        common_support=common, hidden_cells=int(hidden.sum()),
                        assessed_truth=truth, assessed_prediction=assessed,
                        hidden_tickets=hidden_tickets,
                        rank_truth=truth, rank_prediction=assessed,
                        profile_class=CLASS_NAMES[chosen] if model == "rank_profile" else "",
                    ))
                diagnostics.append({
                    "race_id": race_id,
                    "threshold": str(threshold),
                    "common_support": int(common),
                    "hidden_cells": int(hidden.sum()),
                    "newly_hidden": int(newly_hidden.sum()),
                    "true_capped": int(capped.sum()),
                    "hidden_lower_sum": int(hidden_lower.sum()),
                    "residual_lo": residual_lo,
                    "residual_hi": residual_hi,
                    "hidden_tickets": hidden_tickets,
                })
    return rows, diagnostics


def indexed_aggregate(rows):
    return {
        (str(r["sample"]), str(r["threshold"]), str(r["model"]), str(r["common_support"])): r
        for r in aggregate_validation(rows)
    }


def report(old_rows, corrected_rows, diagnostics):
    old = indexed_aggregate(old_rows)
    new = indexed_aggregate(corrected_rows)
    keys = sorted(k for k in new if k[0] in {"clean_2025", "capped_near_tail_2025"})
    lines = [
        "# Symmetric-bound rank-profile validation audit",
        "",
        "Both models receive identical lower and upper bounds. Clean artificial caps use n>=1; "
        "near-tail newly hidden numeric cells use n>=actual_cap_upper+1, while genuine 9999.9 cells retain lower 0.",
        "",
        "| sample | cap | support | model | races | cells | old MAE | corrected MAE | delta | corrected rank MAE |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in keys:
        n = new[key]
        o = old.get(key)
        old_mae = float(o["mae"]) if o else float("nan")
        lines.append(
            f"| {key[0]} | {key[1]} | {'in' if key[3] == '1' else 'out'} | {key[2]} | "
            f"{int(n['races'])} | {int(n['cells'])} | {old_mae:.3f} | {float(n['mae']):.3f} | "
            f"{float(n['mae'])-old_mae:+.3f} | {float(n['rank_mae']):.3f} |"
        )
    lines.extend(["", "## Corrected pairwise direction", ""])
    for sample in ("clean_2025", "capped_near_tail_2025"):
        lines.append(f"### {sample}")
        for threshold in map(str, VALIDATION_THRESHOLDS):
            for support in ("1", "0"):
                rk = new.get((sample, threshold, "rank_profile", support))
                un = new.get((sample, threshold, "uniform", support))
                if not rk or not un:
                    continue
                diff = float(rk["mae"]) - float(un["mae"])
                winner = "rank_profile" if diff < 0 else ("uniform" if diff > 0 else "tie")
                lines.append(
                    f"- cap {threshold}, {'in' if support == '1' else 'out'} support: "
                    f"rank-uniform MAE = {diff:+.3f} -> {winner}"
                )
        lines.append("")
    if diagnostics:
        old_lookup = {
            (str(r["race_id"]), str(r["threshold"])): int(r["hidden_tickets"])
            for r in old_rows
            if str(r["sample"]) == "capped_near_tail_2025" and str(r["model"]) == "rank_profile"
        }
        changes = []
        lower_sums = []
        for d in diagnostics:
            key = (str(d["race_id"]), str(d["threshold"]))
            if key in old_lookup:
                changes.append(int(d["hidden_tickets"]) - old_lookup[key])
            lower_sums.append(int(d["hidden_lower_sum"]))
        changes_sorted = sorted(changes)
        lower_sorted = sorted(lower_sums)
        med_change = changes_sorted[len(changes_sorted)//2] if changes_sorted else 0
        med_lower = lower_sorted[len(lower_sorted)//2] if lower_sorted else 0
        lines.extend([
            "## Near-tail accounting impact", "",
            f"- experiments: {len(diagnostics):,}",
            f"- median newly enforced hidden lower-bound mass: {med_lower:,} tickets",
            f"- median change in chosen hidden-total midpoint versus old calculation: {med_change:+,} tickets",
            f"- min/max midpoint change: {min(changes):+,}/{max(changes):+,} tickets" if changes else "- no matched old rows",
            "",
        ])
    return "\n".join(lines)


def main() -> int:
    data = pathlib.Path("데이터")
    races, feasible, mixture, bounds = fit_mixture(data)
    clean = corrected_clean_rows(races, feasible, mixture, bounds, data)
    near, diagnostics = corrected_near_tail_rows(races, feasible, mixture, bounds, data)
    corrected = clean + near
    old = read_old_rows(data / "rank_profile_validation.csv.gz")
    text = report(old, corrected, diagnostics)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
