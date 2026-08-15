#!/usr/bin/env python3
"""Validate a shifted-power backbone plus empirical tail correction.

The correction curve is learned only from 2022--2024 uncapped races.  For each
training race we fit a shifted power law to the full ordered ticket counts and
store the log residual by fractional rank in the lower-count half.  The median
residual curve is then used as a multiplicative correction to a target race's
shifted-power tail scores.  No 2025 outcome enters the correction.

All 2025 comparisons use the same hidden-ticket total and exactly the same
cellwise lower/upper bounds as the corrected rank-profile audit.
"""
from __future__ import annotations

import pathlib
from collections import defaultdict

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
    load_feasible,
    load_month_grids,
    uncapped_ids,
    validation_row,
)
from kra.feasible import DISPLAY_CAP, capped_ticket_upper


CORRECTION_GRID = np.linspace(0.50, 0.995, 100)


def learn_tail_correction(
    data: pathlib.Path,
    races: dict[str, dict],
    feasible: dict[str, dict[str, int | str]],
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """Learn the median log-residual curve of shifted power laws in the tail."""
    train_ids = uncapped_ids(feasible, years={"2022", "2023", "2024"})
    grids = load_grids(data, races, train_ids)
    curves = []
    tail_r2 = []
    for race_id in sorted(train_ids):
        sales = _won(races[race_id]["sales"]["삼쌍승식"])
        counts, _, _ = reconstruct_counts(sales, grids[race_id])
        ordered = np.sort(counts.astype(float))[::-1]
        ranks = np.arange(1, len(ordered) + 1, dtype=float)
        positive = ordered > 0
        fit = fit_shifted_power(ordered, ranks)
        fitted_log = fit["intercept"] - fit["alpha"] * np.log(ranks + fit["shift"])
        log_residual = np.full(len(ordered), np.nan, dtype=float)
        log_residual[positive] = np.log(ordered[positive]) - fitted_log[positive]
        positions = (ranks - 0.5) / len(ordered)
        keep = positive & (positions >= 0.50)
        if int(keep.sum()) < 10:
            continue
        curve = np.interp(
            CORRECTION_GRID,
            positions[keep],
            log_residual[keep],
            left=float(log_residual[keep][0]),
            right=float(log_residual[keep][-1]),
        )
        curves.append(curve)
        actual = np.log(ordered[keep])
        predicted = fitted_log[keep]
        sse = float(np.square(actual - predicted).sum())
        sst = float(np.square(actual - actual.mean()).sum())
        tail_r2.append(1.0 - sse / sst if sst > 0 else 1.0)
    matrix = np.stack(curves)
    median_curve = np.median(matrix, axis=0)
    # Only relative tail weights matter. Center at the first tail grid point so
    # the correction describes shape rather than an arbitrary common scale.
    median_curve = median_curve - median_curve[0]
    diagnostics = {
        "races": float(len(curves)),
        "median_tail_r2_of_full_shifted_fit": float(np.median(tail_r2)),
    }
    return CORRECTION_GRID.copy(), median_curve, diagnostics


def empirical_tail_factor(
    positions: np.ndarray,
    grid: np.ndarray,
    log_correction: np.ndarray,
) -> np.ndarray:
    correction = np.interp(
        np.asarray(positions, dtype=float),
        grid,
        log_correction,
        left=float(log_correction[0]),
        right=float(log_correction[-1]),
    )
    return np.exp(correction)


def hybrid_cell_scores(
    observed: np.ndarray,
    visible: np.ndarray,
    hidden: np.ndarray,
    combos: list[tuple[int, int, int]],
    horses: list[int],
    grid: np.ndarray,
    log_correction: np.ndarray,
) -> tuple[np.ndarray, dict[str, float]]:
    """Shifted-power tail scores multiplied by the learned empirical correction."""
    head = np.sort(observed[visible].astype(float))[::-1]
    ranks = np.arange(1, len(head) + 1, dtype=float)
    fit = fit_shifted_power(head, ranks)
    tail_ranks = np.arange(len(head) + 1, len(observed) + 1, dtype=float)
    positions = (tail_ranks - 0.5) / len(observed)
    backbone = np.power(tail_ranks + fit["shift"], -fit["alpha"])
    rank_scores = backbone * empirical_tail_factor(positions, grid, log_correction)
    assignment = internal_assignment_scores(combos, observed, visible, hidden, horses)
    order = np.argsort(-assignment, kind="stable")
    cell_scores = np.empty(len(rank_scores), dtype=float)
    cell_scores[order] = rank_scores
    return cell_scores, fit


def hybrid_clean_rows(races, feasible, bounds, data, grid, log_correction):
    rows = []
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
            scores, fit = hybrid_cell_scores(
                observed, visible, hidden, combos, horses, grid, log_correction
            )
            prediction = bounded_weight_allocation_bounds(
                hidden_tickets, scores, hlo, hhi
            )
            rows.append(validation_row(
                sample="clean_2025", race_id=race_id, year="2025",
                threshold=threshold, model="shifted_plus_empirical_tail",
                common_support=common, hidden_cells=int(hidden.sum()),
                assessed_truth=truth[hidden], assessed_prediction=prediction,
                hidden_tickets=hidden_tickets, rank_truth=truth[hidden],
                rank_prediction=prediction,
                profile_class=f"alpha={fit['alpha']:.4f};shift={fit['shift']:.4f}",
            ))
    return rows


def hybrid_near_rows(races, feasible, bounds, data, grid, log_correction):
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
            race = races[race_id]
            info = feasible[race_id]
            values = grids[race_id]
            combos = [combo for combo, _ in values]
            sales = _won(race["sales"]["삼쌍승식"])
            total = sales // 100
            horses = sorted(set(race["horses"]) - set(race.get("scratched") or []))
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
                hlo = np.asarray([
                    0 if capped[i] else actual_upper + 1 for i in hidden_idx
                ], dtype=np.int64)
                hhi = np.asarray([
                    actual_upper if capped[i] else virtual_upper for i in hidden_idx
                ], dtype=np.int64)
                rlo, rhi = hidden_total_interval_bounds(
                    total, lower[visible], upper[visible], hlo, hhi
                )
                hidden_tickets = (rlo + rhi) // 2
                target = np.asarray([
                    0.0 if value == DISPLAY_CAP else 0.73 * total / float(value)
                    for _, value in values
                ])
                observed = np.zeros(len(values), dtype=np.int64)
                observed[visible] = bounded_integer_projection(
                    target[visible], lower[visible], upper[visible], total - hidden_tickets
                )
                scores, fit = hybrid_cell_scores(
                    observed, visible, hidden, combos, horses, grid, log_correction
                )
                prediction = bounded_weight_allocation_bounds(
                    hidden_tickets, scores, hlo, hhi
                )
                newly_local = np.flatnonzero(newly_hidden[hidden])
                assessed = prediction[newly_local]
                truth = lower[newly_hidden]
                rows.append(validation_row(
                    sample="capped_near_tail_2025", race_id=race_id, year="2025",
                    threshold=threshold, model="shifted_plus_empirical_tail",
                    common_support=common, hidden_cells=int(hidden.sum()),
                    assessed_truth=truth, assessed_prediction=assessed,
                    hidden_tickets=hidden_tickets, rank_truth=truth,
                    rank_prediction=assessed,
                    profile_class=f"alpha={fit['alpha']:.4f};shift={fit['shift']:.4f}",
                ))
    return rows


def report(rows, grid, log_correction, diagnostics):
    agg = aggregate_validation(rows)
    lines = [
        "# Shifted-power + empirical-tail hybrid audit",
        "",
        "The empirical correction is learned only from 2022--2024 uncapped races.",
        f"Training races contributing to the correction: {int(diagnostics['races']):,}.",
        "",
        "## Learned tail correction",
        "",
        "A factor above 1 means the observed training tail is heavier than the fitted shifted power law at that rank; below 1 means lighter.",
        "",
        "| rank percentile | multiplicative factor |",
        "| ---: | ---: |",
    ]
    for p in (0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.98, 0.995):
        factor = float(empirical_tail_factor(np.asarray([p]), grid, log_correction)[0])
        lines.append(f"| {100*p:.1f}% | {factor:.4f} |")
    lines.extend([
        "",
        "## Corrected 2025 comparison",
        "",
        "All methods use identical hidden-ticket totals and identical cellwise lower/upper bounds.",
        "",
        "| sample | cap | support | model | races | cells | MAE | rank MAE |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ])
    for row in sorted(agg, key=lambda r: (
        str(r["sample"]), float(r["threshold"]), str(r["common_support"]), str(r["model"])
    )):
        if row["sample"] not in {"clean_2025", "capped_near_tail_2025"}:
            continue
        rank_mae = float(row["rank_mae"]) if row["rank_mae"] is not None else float("nan")
        lines.append(
            f"| {row['sample']} | {row['threshold']} | {'in' if row['common_support']=='1' else 'out'} | "
            f"{row['model']} | {int(row['races'])} | {int(row['cells'])} | "
            f"{float(row['mae']):.3f} | {rank_mae:.3f} |"
        )
    lines.extend(["", "## Winner by MAE", ""])
    grouped = defaultdict(list)
    for row in agg:
        if row["sample"] in {"clean_2025", "capped_near_tail_2025"}:
            grouped[(row["sample"], row["threshold"], row["common_support"])].append(row)
    for key in sorted(grouped, key=lambda k: (k[0], float(k[1]), k[2])):
        best = min(grouped[key], key=lambda r: float(r["mae"]))
        lines.append(
            f"- {key[0]}, cap {key[1]}, {'in' if key[2]=='1' else 'out'} support: "
            f"{best['model']} (MAE {float(best['mae']):.3f})"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    data = pathlib.Path("데이터")
    races, feasible, mixture, bounds, _ = fit_training(data)
    grid, correction, diagnostics = learn_tail_correction(data, races, feasible)

    baseline_clean = corrected_clean_rows(races, feasible, mixture, bounds, data)
    baseline_near, _ = corrected_near_tail_rows(races, feasible, mixture, bounds, data)
    power_clean = power_clean_rows(races, feasible, bounds, data)
    power_near = power_near_rows(races, feasible, bounds, data)
    hybrid_clean = hybrid_clean_rows(races, feasible, bounds, data, grid, correction)
    hybrid_near = hybrid_near_rows(races, feasible, bounds, data, grid, correction)

    rows = baseline_clean + baseline_near + power_clean + power_near + hybrid_clean + hybrid_near
    text = report(rows, grid, correction, diagnostics)
    print(text)
    pathlib.Path("findings/hybrid_tail_audit.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
