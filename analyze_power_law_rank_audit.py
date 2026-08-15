#!/usr/bin/env python3
"""Audit whether trifecta ticket rank-size curves follow power laws.

The audit has two parts.
1. Fit each 2022--2024 uncapped race with a simple power law and a shifted
   power law and summarize fit quality, exponents, and tail fit.
2. Re-run the corrected 2025 artificial-cap validations with four allocation
   rules receiving identical accounting bounds: empirical rank profile,
   simple power law, shifted power law, and uniform.

This script is diagnostic and does not overwrite the maintained artifacts.
"""
from __future__ import annotations

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
from analyze_rank_profile_correction import (
    bounded_weight_allocation_bounds,
    corrected_clean_rows,
    corrected_near_tail_rows,
    hidden_total_interval_bounds,
)
from analyze_rank_profile_imputation import (
    VALIDATION_THRESHOLDS,
    capped_ids,
    complete_visible_counts,
    in_common_support,
    internal_assignment_scores,
    load_feasible,
    load_month_grids,
    support_bounds,
    uncapped_ids,
    validation_row,
    aggregate_validation,
)
from kra.feasible import DISPLAY_CAP, capped_ticket_upper
from kra.rank_profile import fit_rank_profile_mixture, rank_profile


def _linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    xm = float(x.mean())
    ym = float(y.mean())
    denom = float(np.square(x - xm).sum())
    if denom <= 0:
        raise ValueError("degenerate regression")
    slope = float(((x - xm) * (y - ym)).sum() / denom)
    intercept = ym - slope * xm
    residual = y - (intercept + slope * x)
    sse = float(np.square(residual).sum())
    sst = float(np.square(y - ym).sum())
    r2 = 1.0 - sse / sst if sst > 0 else 1.0
    return intercept, slope, sse, r2


def fit_power(counts: np.ndarray, ranks: np.ndarray | None = None) -> dict[str, float]:
    values = np.asarray(counts, dtype=float)
    if ranks is None:
        ranks = np.arange(1, len(values) + 1, dtype=float)
    else:
        ranks = np.asarray(ranks, dtype=float)
    keep = values > 0
    values = values[keep]
    ranks = ranks[keep]
    if len(values) < 4:
        raise ValueError("too few positive cells")
    intercept, slope, sse, r2 = _linear_fit(np.log(ranks), np.log(values))
    n = len(values)
    aic = n * math.log(max(sse / n, 1e-300)) + 2 * 2
    return {
        "intercept": intercept,
        "alpha": -slope,
        "shift": 0.0,
        "sse": sse,
        "r2": r2,
        "aic": aic,
    }


def fit_shifted_power(counts: np.ndarray, ranks: np.ndarray | None = None) -> dict[str, float]:
    values = np.asarray(counts, dtype=float)
    if ranks is None:
        ranks = np.arange(1, len(values) + 1, dtype=float)
    else:
        ranks = np.asarray(ranks, dtype=float)
    keep = values > 0
    values = values[keep]
    ranks = ranks[keep]
    if len(values) < 4:
        raise ValueError("too few positive cells")
    n = len(values)
    max_rank = float(ranks.max())
    candidates = np.unique(np.concatenate((
        np.asarray([0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0]),
        np.geomspace(5.0, max(5.0, max_rank), 48),
    )))
    best = None
    for shift in candidates:
        intercept, slope, sse, r2 = _linear_fit(np.log(ranks + shift), np.log(values))
        if slope >= 0:
            continue
        aic = n * math.log(max(sse / n, 1e-300)) + 2 * 3
        item = {
            "intercept": intercept,
            "alpha": -slope,
            "shift": float(shift),
            "sse": sse,
            "r2": r2,
            "aic": aic,
        }
        if best is None or item["aic"] < best["aic"]:
            best = item
    if best is None:
        raise ValueError("no decreasing shifted-power fit")
    return best


def quantile(values: list[float], p: float) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.quantile(array, p))


def fit_training(data: pathlib.Path):
    races = load_races(data / "races.jsonl.gz")
    feasible = load_feasible(data / "trifecta_feasible_sets.csv.gz")
    train_ids = uncapped_ids(feasible, years={"2022", "2023", "2024"})
    grids = load_grids(data, races, train_ids)
    diagnostics = []
    profiles = []
    metadata = []
    for race_id in sorted(train_ids):
        sales = _won(races[race_id]["sales"]["삼쌍승식"])
        counts, _, _ = reconstruct_counts(sales, grids[race_id])
        ordered = np.sort(counts.astype(float))[::-1]
        pure = fit_power(ordered)
        shifted = fit_shifted_power(ordered)
        cut = len(ordered) // 2
        tail = fit_power(ordered[cut:], np.arange(cut + 1, len(ordered) + 1, dtype=float))
        diagnostics.append({
            "race_id": race_id,
            "starters": int(feasible[race_id]["starters"]),
            "cells": len(ordered),
            "alpha": pure["alpha"],
            "r2": pure["r2"],
            "tail_alpha": tail["alpha"],
            "tail_r2": tail["r2"],
            "shift_alpha": shifted["alpha"],
            "shift": shifted["shift"],
            "shift_r2": shifted["r2"],
            "delta_aic": shifted["aic"] - pure["aic"],
        })
        profiles.append(rank_profile(counts))
        info = feasible[race_id]
        metadata.append({
            "race_id": race_id,
            "starters": int(info["starters"]),
            "density": int(info["total_tickets"]) / int(info["expected_combinations"]),
        })
    mixture = fit_rank_profile_mixture(np.stack(profiles))
    bounds, _ = support_bounds(metadata, mixture.labels)
    return races, feasible, mixture, bounds, diagnostics


def power_cell_scores(
    observed: np.ndarray,
    visible: np.ndarray,
    hidden: np.ndarray,
    combos: list[tuple[int, int, int]],
    horses: list[int],
    *,
    shifted: bool,
) -> tuple[np.ndarray, dict[str, float]]:
    head = np.sort(observed[visible].astype(float))[::-1]
    ranks = np.arange(1, len(head) + 1, dtype=float)
    fit = fit_shifted_power(head, ranks) if shifted else fit_power(head, ranks)
    tail_ranks = np.arange(len(head) + 1, len(observed) + 1, dtype=float)
    scores = np.power(tail_ranks + fit["shift"], -fit["alpha"])
    assignment = internal_assignment_scores(combos, observed, visible, hidden, horses)
    order = np.argsort(-assignment, kind="stable")
    cell_scores = np.empty(len(scores), dtype=float)
    cell_scores[order] = scores
    return cell_scores, fit


def power_clean_rows(races, feasible, bounds, data: pathlib.Path):
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
            for name, shifted in (("power_law", False), ("shifted_power_law", True)):
                scores, fit = power_cell_scores(
                    observed, visible, hidden, combos, horses, shifted=shifted
                )
                prediction = bounded_weight_allocation_bounds(
                    hidden_tickets, scores, hlo, hhi
                )
                rows.append(validation_row(
                    sample="clean_2025", race_id=race_id, year="2025",
                    threshold=threshold, model=name, common_support=common,
                    hidden_cells=int(hidden.sum()), assessed_truth=truth[hidden],
                    assessed_prediction=prediction, hidden_tickets=hidden_tickets,
                    rank_truth=truth[hidden], rank_prediction=prediction,
                    profile_class=f"alpha={fit['alpha']:.4f};shift={fit['shift']:.4f}",
                ))
    return rows


def power_near_rows(races, feasible, bounds, data: pathlib.Path):
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
                newly_local = np.flatnonzero(newly_hidden[hidden])
                truth = lower[newly_hidden]
                for name, shifted in (("power_law", False), ("shifted_power_law", True)):
                    scores, fit = power_cell_scores(
                        observed, visible, hidden, combos, horses, shifted=shifted
                    )
                    prediction = bounded_weight_allocation_bounds(
                        hidden_tickets, scores, hlo, hhi
                    )
                    assessed = prediction[newly_local]
                    rows.append(validation_row(
                        sample="capped_near_tail_2025", race_id=race_id, year="2025",
                        threshold=threshold, model=name, common_support=common,
                        hidden_cells=int(hidden.sum()), assessed_truth=truth,
                        assessed_prediction=assessed, hidden_tickets=hidden_tickets,
                        rank_truth=truth, rank_prediction=assessed,
                        profile_class=f"alpha={fit['alpha']:.4f};shift={fit['shift']:.4f}",
                    ))
    return rows


def report_training(diag):
    lines = [
        "# Power-law rank-size audit",
        "",
        "## 2022--2024 uncapped training races",
        "",
        f"Races: {len(diag):,}",
        "",
        "| statistic | simple power law | tail-half simple power law | shifted power law |",
        "| --- | ---: | ---: | ---: |",
        f"| median R2 | {quantile([d['r2'] for d in diag], .5):.5f} | {quantile([d['tail_r2'] for d in diag], .5):.5f} | {quantile([d['shift_r2'] for d in diag], .5):.5f} |",
        f"| 25th percentile R2 | {quantile([d['r2'] for d in diag], .25):.5f} | {quantile([d['tail_r2'] for d in diag], .25):.5f} | {quantile([d['shift_r2'] for d in diag], .25):.5f} |",
        f"| share R2 >= .95 | {np.mean([d['r2'] >= .95 for d in diag]):.1%} | {np.mean([d['tail_r2'] >= .95 for d in diag]):.1%} | {np.mean([d['shift_r2'] >= .95 for d in diag]):.1%} |",
        f"| median alpha | {quantile([d['alpha'] for d in diag], .5):.4f} | {quantile([d['tail_alpha'] for d in diag], .5):.4f} | {quantile([d['shift_alpha'] for d in diag], .5):.4f} |",
        "",
        f"Shifted law AIC-better share: {np.mean([d['delta_aic'] < -2 for d in diag]):.1%}",
        f"; median delta AIC (shifted - simple): {quantile([d['delta_aic'] for d in diag], .5):.2f}",
        f"; median fitted shift: {quantile([d['shift'] for d in diag], .5):.3f}",
        "",
    ]
    return lines


def report_validation(rows):
    agg = aggregate_validation(rows)
    lines = [
        "## Corrected 2025 reconstruction comparison",
        "",
        "All four methods use the same hidden-ticket total and identical cellwise lower/upper bounds.",
        "",
        "| sample | cap | support | model | races | cells | MAE | rank MAE |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in sorted(agg, key=lambda r: (
        str(r["sample"]), float(r["threshold"]), str(r["common_support"]), str(r["model"])
    )):
        if row["sample"] not in {"clean_2025", "capped_near_tail_2025"}:
            continue
        lines.append(
            f"| {row['sample']} | {row['threshold']} | {'in' if row['common_support']=='1' else 'out'} | {row['model']} | "
            f"{int(row['races'])} | {int(row['cells'])} | {float(row['mae']):.3f} | "
            f"{float(row['rank_mae']) if row['rank_mae'] is not None else float('nan'):.3f} |"
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
    return lines


def main() -> int:
    data = pathlib.Path("데이터")
    races, feasible, mixture, bounds, diag = fit_training(data)
    baseline_clean = corrected_clean_rows(races, feasible, mixture, bounds, data)
    baseline_near, _ = corrected_near_tail_rows(races, feasible, mixture, bounds, data)
    power_clean = power_clean_rows(races, feasible, bounds, data)
    power_near = power_near_rows(races, feasible, bounds, data)
    rows = baseline_clean + baseline_near + power_clean + power_near
    lines = report_training(diag) + report_validation(rows)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
