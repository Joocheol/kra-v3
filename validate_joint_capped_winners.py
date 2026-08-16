#!/usr/bin/env python3
"""External check of the joint tail reconstruction on real capped winners.

The cross-pool coefficients are re-fitted on 2022--2024 artificial 7000x
censoring without using any race outcomes.  They are then frozen and applied
to real 2025 trifecta grids containing 9999.9.  Only after prediction do we
join KRA's frozen winning-payout table, which point-identifies the ticket count
for the realised capped cell.  This winner-only sample is selection-biased and
is used strictly as an external accuracy diagnostic, never for fitting.
"""
from __future__ import annotations

import csv
import gzip
import math
import pathlib
import statistics

import numpy as np
from scipy.special import logsumexp

from analyze_cross_market import load_feasible, load_race_records
from analyze_joint_reconstruction import (
    FEATURE_MODELS,
    build_experiment,
    fit_coefficients,
)
from analyze_masked_reconstruction import (
    ModelUnavailable,
    bounded_integer_projection,
    load_cross_pool_odds,
    load_grids,
    model_scores,
    primary_race_ids,
)
from check_coherence import load_month

THRESHOLD = 7000.0
CROSS_COLUMNS = (2, 3, 4)  # win_harville, exacta_then_third, trio_then_order


def load_winner_truth(path: pathlib.Path) -> list[dict[str, object]]:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if (
                row["pool"] == "trifecta"
                and row["race_date"][:4] == "2025"
                and row["ticket_count"]
                and row["is_above_display_cap"] == "1"
            ):
                rows.append({
                    "race_id": row["race_id"],
                    "combo": (int(row["first_no"]), int(row["second_no"]), int(row["third_no"])),
                    "actual_odds": float(row["actual_odds"]),
                    "truth": int(row["ticket_count"]),
                })
    return rows


def market_cross_pool(market: dict) -> dict[str, dict[tuple[int, ...], float]]:
    return {
        "단승식": {(int(h),): float(v) for h, v in market["win"].items()},
        "쌍승식": {tuple(map(int, k)): float(v) for k, v in market["exacta"].items()},
        "삼복승식": {tuple(sorted(map(int, k))): float(v) for k, v in market["trio"].items()},
    }


def predict_capped(
    race: dict,
    market: dict,
    info: dict[str, int],
    coef: np.ndarray,
) -> tuple[dict[tuple[int, int, int], int], dict[tuple[int, int, int], int]]:
    odds = market["trifecta"]
    combos = sorted(odds)
    masked = np.asarray([float(odds[c]) == 9999.9 for c in combos], dtype=bool)
    if int(masked.sum()) != info["capped_cells"]:
        raise ValueError(f"{race['race_id']}: capped cell count mismatch")
    visible = ~masked
    active = sorted(set(race["horses"]) - set(race.get("scratched") or []))
    cross = market_cross_pool(market)
    dummy_counts = np.zeros(len(combos), dtype=np.int64)
    columns = []
    for model in FEATURE_MODELS:
        if model not in {"win_harville", "exacta_then_third", "trio_then_order"}:
            continue
        score = model_scores(
            model, combos, dummy_counts, visible, masked, active,
            cross_pool=cross,
        )
        if np.any(score <= 0) or not np.isfinite(score).all():
            raise ModelUnavailable(f"invalid score for {model}")
        log_score = np.log(score)
        columns.append(log_score - log_score.mean())
    x = np.column_stack(columns)
    logits = x @ coef
    probs = np.exp(logits - logsumexp(logits))
    residual = info["residual_mid"]
    upper = np.full(int(masked.sum()), info["cap_upper"], dtype=np.int64)
    zero = np.zeros(int(masked.sum()), dtype=np.int64)
    joint = bounded_integer_projection(residual * probs, zero, upper, residual)
    uniform_prob = np.full(int(masked.sum()), 1.0 / int(masked.sum()))
    uniform = bounded_integer_projection(residual * uniform_prob, zero, upper, residual)
    hidden = [c for c, m in zip(combos, masked) if m]
    return dict(zip(hidden, uniform)), dict(zip(hidden, joint))


def main() -> int:
    data = pathlib.Path("데이터")
    races = load_race_records(data / "races.jsonl.gz")

    # Fit once on pre-2025 pseudo-censoring only.
    primary = primary_race_ids(data / "trifecta_feasible_sets.csv.gz")
    grids = load_grids(data, races, primary)
    cross_odds = load_cross_pool_odds(data, primary)
    train = []
    for race_id in sorted(primary):
        if races[race_id]["date"][:4] > "2024":
            continue
        exp = build_experiment(
            races[race_id], grids[race_id], cross_odds.get(race_id, {}), THRESHOLD
        )
        if exp is not None:
            train.append(exp)
    coef, train_ce = fit_coefficients(train, CROSS_COLUMNS)

    feasible = load_feasible(data / "trifecta_feasible_sets.csv.gz")
    truth_rows = load_winner_truth(data / "winning_capped_payouts.csv.gz")
    by_month = {}
    results = []
    excluded = []
    for truth in truth_rows:
        race_id = str(truth["race_id"])
        race = races[race_id]
        month = race["date"][:7]
        if month not in by_month:
            by_month[month] = load_month(data, month)
        market = by_month[month].get(race_id)
        info = feasible.get(race_id)
        if market is None or info is None:
            excluded.append((race_id, "missing market/feasible"))
            continue
        try:
            uniform, joint = predict_capped(race, market, info, coef)
        except (ModelUnavailable, ValueError, KeyError, ZeroDivisionError) as exc:
            excluded.append((race_id, str(exc)))
            continue
        combo = truth["combo"]
        if combo not in joint:
            excluded.append((race_id, "winner is not a capped trifecta cell"))
            continue
        y = int(truth["truth"])
        u = int(uniform[combo])
        j = int(joint[combo])
        results.append((race_id, float(truth["actual_odds"]), y, u, j))

    print("fit_threshold,train_races,train_ce,coef")
    print(
        f"{THRESHOLD:.0f},{len(train)},{train_ce:.6f},"
        + ";".join(
            f"{FEATURE_MODELS[c]}={v:.6f}" for c, v in zip(CROSS_COLUMNS, coef)
        )
    )
    print("race_id,actual_odds,true_tickets,uniform_pred,joint_pred,uniform_abs_error,joint_abs_error,uniform_abs_rel,joint_abs_rel")
    for race_id, payout, truth, uniform, joint in results:
        print(
            f"{race_id},{payout:.1f},{truth},{uniform},{joint},"
            f"{abs(uniform-truth)},{abs(joint-truth)},"
            f"{abs(uniform-truth)/truth:.6f},{abs(joint-truth)/truth:.6f}"
        )
    if not results:
        raise ValueError(f"no externally validated rows; exclusions={excluded}")
    u_abs = [abs(u-y) for _, _, y, u, _ in results]
    j_abs = [abs(j-y) for _, _, y, _, j in results]
    u_rel = [abs(u-y)/y for _, _, y, u, _ in results]
    j_rel = [abs(j-y)/y for _, _, y, _, j in results]
    print(
        "SUMMARY "
        f"n={len(results)} excluded={len(excluded)} "
        f"uniform_MAE={statistics.mean(u_abs):.3f} joint_MAE={statistics.mean(j_abs):.3f} "
        f"uniform_MdAPE={statistics.median(u_rel):.4%} joint_MdAPE={statistics.median(j_rel):.4%} "
        f"uniform_maxAPE={max(u_rel):.4%} joint_maxAPE={max(j_rel):.4%} "
        f"joint_better={sum(j < u for j,u in zip(j_abs,u_abs))}/{len(results)}"
    )
    if excluded:
        print("EXCLUDED " + " | ".join(f"{race}:{reason}" for race, reason in excluded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
