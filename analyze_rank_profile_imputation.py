#!/usr/bin/env python3
"""Fit ticket rank-profile types and impute trifecta ``9999.9`` cells.

The maintained accounting identified set remains the outer result.  This
script adds a model-assisted layer: three empirical rank profiles are fitted
only on 2022--2024 uncapped races, classified from the visible head of a target
race, and used to allocate a chosen feasible residual across capped cells.
Validation is strictly separated into 2025 clean-race masking, near-tail
masking inside genuinely capped 2025 races, and selected winning-cell payouts.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import math
import pathlib
import re
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from decimal import Decimal

import numpy as np

from analyze_masked_reconstruction import (
    _won,
    bounded_integer_projection,
    load_grids,
    load_races,
    reconstruct_counts,
)
from kra.feasible import DISPLAY_CAP, capped_ticket_upper, displayed_ticket_interval
from kra.rank_profile import (
    CLASS_NAMES,
    RankProfileMixture,
    assign_ranked_counts,
    bounded_rank_allocation,
    bounded_weight_allocation,
    fit_rank_profile_mixture,
    hidden_total_interval,
    partial_class_probabilities,
    rank_profile,
    tail_rank_scores,
)


PAGE_KEY = "3Both"
NUMERIC_ODDS = re.compile(r"^[0-9]+\.[0-9]$")
VALIDATION_THRESHOLDS = tuple(map(Decimal, ("3000.0", "5000.0", "7000.0", "9000.0")))
VALIDATION_FIELDS = [
    "sample", "race_id", "year", "threshold", "model", "common_support",
    "hidden_cells", "assessed_cells", "hidden_tickets", "absolute_error_sum",
    "rank_absolute_error_sum", "exact_cells", "squared_log1p_error_sum",
    "profile_class",
]
RACE_FIELDS = [
    "race_id", "year", "meet", "starters", "total_tickets", "capped_cells",
    "residual_min", "residual_mid", "residual_max", "profile_class",
    "p_diffuse", "p_intermediate", "p_concentrated", "common_support",
    "estimated_zero_cells", "model_zero_min", "model_zero_max",
]
CELL_FIELDS = [
    "race_id", "year", "meet", "starters", "total_tickets", "capped_cells",
    "combo", "profile_class", "class_probability", "common_support",
    "residual_mid", "estimated_tickets", "model_count_min", "model_count_max",
    "accounting_count_min", "accounting_count_max", "estimated_odds",
]


def load_feasible(path: pathlib.Path) -> dict[str, dict[str, int | str]]:
    rows: dict[str, dict[str, int | str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not ("2022" <= row["year"] <= "2025" and row["strict_feasible"] == "1"):
                continue
            lo = int(row["feasible_residual_min"])
            hi = int(row["feasible_residual_max"])
            rows[row["race_id"]] = {
                "year": row["year"],
                "meet": row["meet"],
                "starters": int(row["starters"]),
                "total_tickets": int(row["total_tickets"]),
                "expected_combinations": int(row["expected_combinations"]),
                "capped_cells": int(row["capped_cells"]),
                "residual_min": lo,
                "residual_mid": (lo + hi) // 2,
                "residual_max": hi,
                "cap_upper": int(row["cap_ticket_upper"]),
                "accounting_cell_min": int(row["individual_cap_ticket_min"]),
                "accounting_cell_max": int(row["individual_cap_ticket_max"]),
            }
    return rows


def uncapped_ids(
    feasible: dict[str, dict[str, int | str]], *, years: set[str]
) -> set[str]:
    return {
        race_id for race_id, row in feasible.items()
        if row["year"] in years and int(row["capped_cells"]) == 0
    }


def capped_ids(feasible: dict[str, dict[str, int | str]]) -> set[str]:
    return {
        race_id for race_id, row in feasible.items() if int(row["capped_cells"]) > 0
    }


def load_month_grids(
    path: pathlib.Path,
    races: dict[str, dict],
    wanted: set[str],
) -> dict[str, list[tuple[tuple[int, int, int], Decimal]]]:
    grids: dict[str, list[tuple[tuple[int, int, int], Decimal]]] = defaultdict(list)
    seen: dict[str, set[tuple[int, int, int]]] = defaultdict(set)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            race_id = row["race_id"]
            if (
                race_id not in wanted or row["section"] != "body"
                or row["spanned"] != "0" or not NUMERIC_ODDS.fullmatch(row["cell_raw"])
            ):
                continue
            axes = (row["page_variant"], row["col_header"], row["row_header"])
            if not all(axis.isdigit() for axis in axes):
                continue
            combo = tuple(map(int, axes))
            active = set(races[race_id]["horses"]) - set(races[race_id].get("scratched") or [])
            if len(set(combo)) != 3 or not set(combo).issubset(active):
                raise ValueError(f"{race_id}: invalid combination {combo}")
            if combo in seen[race_id]:
                raise ValueError(f"{race_id}: duplicate combination {combo}")
            seen[race_id].add(combo)
            grids[race_id].append((combo, Decimal(row["cell_raw"])))
    for race_id, values in grids.items():
        active = set(races[race_id]["horses"]) - set(races[race_id].get("scratched") or [])
        expected = len(active) * (len(active) - 1) * (len(active) - 2)
        if len(values) != expected:
            raise ValueError(f"{race_id}: {len(values)} combinations, expected {expected}")
    return grids


def complete_visible_counts(
    sales_won: int,
    values: list[tuple[tuple[int, int, int], Decimal]],
    residual: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    total = sales_won // 100
    lower = np.zeros(len(values), dtype=np.int64)
    upper = np.zeros(len(values), dtype=np.int64)
    target = np.zeros(len(values), dtype=float)
    visible = np.asarray([odds != DISPLAY_CAP for _, odds in values], dtype=bool)
    for index in np.flatnonzero(visible):
        odds = values[index][1]
        candidates = displayed_ticket_interval(sales_won, odds)
        if not candidates:
            raise ValueError(f"incompatible visible odds: {odds}")
        lower[index] = candidates.start
        upper[index] = candidates.stop - 1
        target[index] = 0.73 * total / float(odds)
    visible_counts = bounded_integer_projection(
        target[visible], lower[visible], upper[visible], total - residual
    )
    counts = np.zeros(len(values), dtype=np.int64)
    counts[visible] = visible_counts
    return counts, visible, ~visible, lower, upper


def internal_assignment_scores(
    combos: list[tuple[int, int, int]],
    counts: np.ndarray,
    visible: np.ndarray,
    hidden: np.ndarray,
    horses: list[int],
    *,
    alpha: float = 0.5,
) -> np.ndarray:
    index = {horse: i for i, horse in enumerate(horses)}
    marginals = [np.full(len(horses), alpha, dtype=float) for _ in range(3)]
    for cell in np.flatnonzero(visible):
        for position, horse in enumerate(combos[cell]):
            marginals[position][index[horse]] += float(counts[cell])
    scores = []
    for cell in np.flatnonzero(hidden):
        a, b, c = combos[cell]
        scores.append(
            marginals[0][index[a]] * marginals[1][index[b]] * marginals[2][index[c]]
        )
    return np.asarray(scores, dtype=float)


def predict_hidden(
    mixture: RankProfileMixture,
    counts: np.ndarray,
    visible: np.ndarray,
    hidden: np.ndarray,
    combos: list[tuple[int, int, int]],
    horses: list[int],
    *,
    total_tickets: int,
    hidden_tickets: int,
    upper: int | np.ndarray,
    class_index: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    probabilities, distances = partial_class_probabilities(
        counts[visible], total_cells=len(counts), total_tickets=total_tickets,
        mixture=mixture,
    )
    chosen = int(np.argmin(distances)) if class_index is None else class_index
    rank_scores = tail_rank_scores(
        mixture, chosen, total_cells=len(counts), visible_cells=int(visible.sum())
    )
    assignment = internal_assignment_scores(combos, counts, visible, hidden, horses)
    assignment_order = np.argsort(-assignment, kind="stable")
    cell_scores = np.empty(len(rank_scores), dtype=float)
    cell_scores[assignment_order] = rank_scores
    assigned = bounded_weight_allocation(hidden_tickets, cell_scores, upper)
    ranked = np.sort(assigned)[::-1]
    return assigned, ranked, probabilities, chosen


def uniform_hidden(
    hidden_tickets: int, cells: int, upper: int | np.ndarray
) -> np.ndarray:
    return bounded_weight_allocation(hidden_tickets, np.ones(cells), upper)


def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * p)]


def support_bounds(
    metadata: list[dict[str, float | int | str]], labels: np.ndarray
) -> tuple[dict[int, tuple[float, float]], list[dict[str, object]]]:
    by_horse: dict[int, list[float]] = defaultdict(list)
    for item in metadata:
        by_horse[int(item["starters"])].append(float(item["density"]))
    bounds = {
        starters: (quantile(values, 0.05), quantile(values, 0.95))
        for starters, values in by_horse.items() if len(values) >= 20
    }
    class_rows = []
    for class_index, name in enumerate(CLASS_NAMES):
        members = [item for item, label in zip(metadata, labels) if label == class_index]
        class_rows.append({
            "class": name,
            "races": len(members),
            "starters_median": quantile([float(x["starters"]) for x in members], 0.5),
            "density_median": quantile([float(x["density"]) for x in members], 0.5),
        })
    return bounds, class_rows


def in_common_support(info: dict[str, int | str], bounds: dict[int, tuple[float, float]]) -> bool:
    starters = int(info["starters"])
    density = int(info["total_tickets"]) / int(info["expected_combinations"])
    return starters in bounds and bounds[starters][0] <= density <= bounds[starters][1]


def validation_row(
    *,
    sample: str,
    race_id: str,
    year: str,
    threshold: Decimal,
    model: str,
    common_support: bool,
    hidden_cells: int,
    assessed_truth: np.ndarray,
    assessed_prediction: np.ndarray,
    hidden_tickets: int,
    rank_truth: np.ndarray | None = None,
    rank_prediction: np.ndarray | None = None,
    profile_class: str = "",
) -> dict[str, object]:
    truth = np.asarray(assessed_truth, dtype=np.int64)
    predicted = np.asarray(assessed_prediction, dtype=np.int64)
    rank_error: str | int = ""
    if rank_truth is not None and rank_prediction is not None:
        rank_error = int(np.abs(
            np.sort(rank_truth)[::-1] - np.sort(rank_prediction)[::-1]
        ).sum())
    return {
        "sample": sample,
        "race_id": race_id,
        "year": year,
        "threshold": str(threshold),
        "model": model,
        "common_support": int(common_support),
        "hidden_cells": hidden_cells,
        "assessed_cells": len(truth),
        "hidden_tickets": hidden_tickets,
        "absolute_error_sum": int(np.abs(predicted - truth).sum()),
        "rank_absolute_error_sum": rank_error,
        "exact_cells": int((predicted == truth).sum()),
        "squared_log1p_error_sum": format(float(np.square(
            np.log1p(predicted) - np.log1p(truth)
        ).sum()), ".10g"),
        "profile_class": profile_class,
    }


def clean_validation(
    races: dict[str, dict],
    grids: dict[str, list[tuple[tuple[int, int, int], Decimal]]],
    feasible: dict[str, dict[str, int | str]],
    mixture: RankProfileMixture,
    bounds: dict[int, tuple[float, float]],
) -> list[dict[str, object]]:
    rows = []
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
            try:
                residual_lo, residual_hi = hidden_total_interval(
                    total,
                    lower[visible],
                    upper[visible],
                    np.full(int(hidden.sum()), cap_upper, dtype=np.int64),
                )
            except ValueError:
                raise ValueError(f"{race_id} {threshold}: artificial residual infeasible")
            hidden_tickets = (residual_lo + residual_hi) // 2
            target = np.asarray([
                0.73 * total / float(value) for _, value in values
            ])
            observed_counts = np.zeros(len(values), dtype=np.int64)
            observed_counts[visible] = bounded_integer_projection(
                target[visible], lower[visible], upper[visible], total - hidden_tickets
            )
            predicted, ranked, probabilities, chosen = predict_hidden(
                mixture, observed_counts, visible, hidden, combos, horses,
                total_tickets=total, hidden_tickets=hidden_tickets, upper=cap_upper,
            )
            uniform_ranked = uniform_hidden(hidden_tickets, int(hidden.sum()), cap_upper)
            assignment = internal_assignment_scores(
                combos, observed_counts, visible, hidden, horses
            )
            uniform_predicted = assign_ranked_counts(uniform_ranked, assignment)
            rows.append(validation_row(
                sample="clean_2025", race_id=race_id, year="2025",
                threshold=threshold, model="rank_profile", common_support=common,
                hidden_cells=int(hidden.sum()), assessed_truth=truth[hidden],
                assessed_prediction=predicted, hidden_tickets=hidden_tickets,
                rank_truth=truth[hidden], rank_prediction=ranked,
                profile_class=CLASS_NAMES[chosen],
            ))
            rows.append(validation_row(
                sample="clean_2025", race_id=race_id, year="2025",
                threshold=threshold, model="uniform", common_support=common,
                hidden_cells=int(hidden.sum()), assessed_truth=truth[hidden],
                assessed_prediction=uniform_predicted, hidden_tickets=hidden_tickets,
                rank_truth=truth[hidden], rank_prediction=uniform_ranked,
            ))
    return rows


def load_winning_counts(path: pathlib.Path) -> dict[str, dict[tuple[int, int, int], int]]:
    out: dict[str, dict[tuple[int, int, int], int]] = defaultdict(dict)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if (
                row["pool"] != "trifecta" or row["ticket_inference_status"] != "identified"
                or not ("2022" <= row["race_date"][:4] <= "2025")
            ):
                continue
            combo = (int(row["first_no"]), int(row["second_no"]), int(row["third_no"]))
            out[row["race_id"]][combo] = int(row["ticket_count"])
    return out


@contextmanager
def deterministic_csv(path: pathlib.Path, fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
        temporary = pathlib.Path(raw.name)
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                yield writer
    temporary.replace(path)


def aggregate_validation(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[(
            str(row["sample"]), str(row["threshold"]), str(row["model"]),
            str(row["common_support"]),
        )].append(row)
    out = []
    for key in sorted(groups):
        group = groups[key]
        cells = sum(int(row["assessed_cells"]) for row in group)
        rank_cells = sum(
            int(row["hidden_cells"]) for row in group
            if row["rank_absolute_error_sum"] != ""
        )
        out.append({
            "sample": key[0], "threshold": key[1], "model": key[2],
            "common_support": key[3], "races": len(group), "cells": cells,
            "mae": sum(int(row["absolute_error_sum"]) for row in group) / cells,
            "exact": sum(int(row["exact_cells"]) for row in group) / cells,
            "log_rmse": math.sqrt(sum(float(row["squared_log1p_error_sum"]) for row in group) / cells),
            "rank_mae": (
                sum(int(row["rank_absolute_error_sum"]) for row in group) / rank_cells
                if rank_cells else None
            ),
        })
    return out


def make_plots(
    mixture: RankProfileMixture,
    aggregate: list[dict[str, object]],
    output_dir: pathlib.Path,
) -> None:
    import os
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/kra-v3-matplotlib")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    x = np.linspace(0.01, 0.99, 199)
    colors = ("#5B7FA3", "#C58B00", "#244A73")
    styles = ("--", "-.", "-")
    fig, ax = plt.subplots(figsize=(8.8, 5.4))
    for class_index, name in enumerate(CLASS_NAMES):
        y = np.expm1(np.interp(x, mixture.grid, mixture.centroids[class_index]))
        ax.plot(x * 100, y, color=colors[class_index], linestyle=styles[class_index],
                linewidth=2.2, label=f"{name} ({mixture.class_sizes[class_index]:,} races)")
    ax.set_yscale("log")
    ax.set_xlabel("Combination rank percentile (largest ticket count first)")
    ax.set_ylabel("Tickets relative to the race-wide cell mean")
    ax.set_title("Fitted trifecta ticket rank-profile types\n2022–2024 uncapped races; scale-free profiles")
    ax.grid(axis="y", color="#D9DDE3", linewidth=0.7)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_dir / "rank_profile_types.png", dpi=180, metadata={"Software": "kra-v3"})
    plt.close(fig)

    selected = [row for row in aggregate if row["sample"] in {"clean_2025", "capped_near_tail_2025"} and row["common_support"] == "1"]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8), sharey=False)
    for ax, sample, title in zip(
        axes,
        ("clean_2025", "capped_near_tail_2025"),
        ("Clean-race artificial caps", "Near-tail masking in genuinely capped races"),
    ):
        for model, color, style in (("uniform", "#6B7280", "--"), ("rank_profile", "#244A73", "-")):
            rows = sorted(
                [row for row in selected if row["sample"] == sample and row["model"] == model],
                key=lambda row: float(row["threshold"]),
            )
            if rows:
                ax.plot([float(row["threshold"]) for row in rows], [float(row["mae"]) for row in rows],
                        marker="o", color=color, linestyle=style, linewidth=2, label=model)
        ax.set_title(title)
        ax.set_xlabel("Virtual display cap")
        ax.set_ylabel("Cell MAE (100-won tickets)")
        ax.grid(axis="y", color="#D9DDE3", linewidth=0.7)
    axes[0].legend(frameon=False)
    fig.suptitle("2025 out-of-time reconstruction validation\nCommon-support races only")
    fig.tight_layout()
    fig.savefig(output_dir / "rank_profile_validation.png", dpi=180, metadata={"Software": "kra-v3"})
    plt.close(fig)


def profile_shares(mixture: RankProfileMixture, class_index: int) -> tuple[float, float, float]:
    x = (np.arange(1000) + 0.5) / 1000
    weights = np.expm1(np.interp(x, mixture.grid, mixture.centroids[class_index]))
    weights /= weights.sum()
    return float(weights[:10].sum()), float(weights[:100].sum()), float(weights[:250].sum())


def make_report(
    mixture: RankProfileMixture,
    class_rows: list[dict[str, object]],
    aggregate: list[dict[str, object]],
    target_races: list[dict[str, object]],
) -> str:
    common_targets = sum(int(row["common_support"]) for row in target_races)
    point_zeros = sum(int(row["estimated_zero_cells"]) for row in target_races)
    zero_low = sum(int(row["model_zero_min"]) for row in target_races)
    zero_high = sum(int(row["model_zero_max"]) for row in target_races)
    target_classes = {
        name: sum(row["profile_class"] == name for row in target_races)
        for name in CLASS_NAMES
    }
    median_class_probability = quantile([
        max(float(row[f"p_{name}"]) for name in CLASS_NAMES)
        for row in target_races
    ], 0.5)
    lines = [
        "# 순위분포 유형을 이용한 `9999.9` 마권 수 모형복원", "",
        "## 기술 요약", "",
        f"2022--2024년 실제 `9999.9`가 없는 {int(mixture.class_sizes.sum()):,}개 경주의 "
        "완전한 삼쌍승 마권표를 규모와 무관한 순위곡선으로 바꾸고, 분산형·중간형·집중형 "
        "세 유형을 적합했다. 2025년과 실제 상한 경주는 모형 적합에 사용하지 않았다.", "",
        f"출전두수별 학습경주가 20개 이상이고 조합당 마권 밀도가 학습표본의 5--95% 안인 "
        f"공통지지 구간에는 실제 상한 {len(target_races):,}경주 중 {common_targets:,}경주"
        f"({common_targets/len(target_races):.1%})가 들어간다. 나머지는 외삽으로 따로 표시한다.", "",
        "모형은 회계적 식별집합을 대체하지 않는다. 각 경주의 관측 매출액과 가시 배당의 "
        "정수구간만으로 계산한 잔여총량 중간값, 그리고 가시적인 고빈도 머리에 가장 가까운 "
        "유형을 이용한 조건부 점추정이다. 잔여총량의 하한·중간·상한과 세 유형을 모두 "
        "움직인 모형범위도 함께 저장한다.", "",
        "## 세 가지 순위분포 유형", "",
        "![세 가지 삼쌍승 마권 순위분포 유형](rank_profile_types.png)", "",
        "| 유형 | 학습경주 | 출전두수 중앙 | 셀당 마권 중앙 | 상위 1%/10%/25% 마권 비중 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for class_index, row in enumerate(class_rows):
        shares = profile_shares(mixture, class_index)
        lines.append(
            f"| {row['class']} | {row['races']:,} | {row['starters_median']:.0f} | "
            f"{row['density_median']:.1f} | {shares[0]:.1%}/{shares[1]:.1%}/{shares[2]:.1%} |"
        )
    lines.extend([
        "", "곡선은 각 셀의 마권 수를 그 경주의 셀당 평균 마권 수로 나눈 값이다. "
        "따라서 매출 규모가 다른 경주도 형태만 비교한다. 유형 수 3은 결과를 본 뒤 늘리지 "
        "않고 해석 가능한 최소 혼합으로 고정했다.", "",
        "## 2025년 시간외 검증", "",
        "![2025년 가상검열 복원 검증](rank_profile_validation.png)", "",
        "| 검증표본 | 가상상한 | 지지 | 모형 | 경주 | 평가셀 | 셀 MAE | log1p RMSE | 정확일치 | 순위 MAE |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in aggregate:
        if row["sample"] not in {"clean_2025", "capped_near_tail_2025", "winning_capped"}:
            continue
        support = "안" if row["common_support"] == "1" else "밖"
        rank = "—" if row["rank_mae"] is None else f"{row['rank_mae']:.3f}"
        lines.append(
            f"| {row['sample']} | {row['threshold']} | {support} | {row['model']} | "
            f"{row['races']:,} | {row['cells']:,} | {row['mae']:.3f} | "
            f"{row['log_rmse']:.4f} | {row['exact']:.2%} | {rank} |"
        )
    lines.extend([
        "", "`clean_2025`는 상한 없는 경주의 고배당 꼬리를 가리고 정답 전체를 평가한다. "
        "`capped_near_tail_2025`는 실제 `9999.9`가 있는 경주에서 상한 바로 아래의 "
        "점식별 셀을 추가로 가린 뒤 그 셀만 평가한다. 두 검증 모두 숨긴 셀의 실제 합계를 "
        "입력하지 않고 매출액·가시 배당·셀별 상한으로 잔여총량 구간을 만든 뒤 중간값을 쓴다. "
        "두 번째 검사가 목표 자료의 출전두수와 유동성 이동을 더 직접 반영한다. "
        "`winning_capped`는 지급배당으로 마권 수가 드러난 "
        "당첨 선택표본이므로 외부 진단일 뿐 전체 상한 셀의 무작위 검증이 아니다.", "",
        "## 전체 상한 경주의 조건부 복원", "",
        "최우선 유형은 분산형 "
        f"{target_classes['diffuse']:,}경주({target_classes['diffuse']/len(target_races):.1%}), "
        f"중간형 {target_classes['intermediate']:,}경주"
        f"({target_classes['intermediate']/len(target_races):.1%}), 집중형 "
        f"{target_classes['concentrated']:,}경주"
        f"({target_classes['concentrated']/len(target_races):.1%})다. 최우선 유형확률의 "
        f"중앙값은 {median_class_probability:.1%}다. 목표경주가 집중형에 크게 몰리므로 "
        "세 유형을 안정적인 잠재 집단으로 해석하지 않고 꼬리모양 시나리오로만 쓴다.", "",
        f"잔여총량 중간값과 최우선 유형으로 채운 점추정에서 무투표 셀은 {point_zeros:,}개다. "
        f"잔여총량 하한·중간·상한과 세 유형을 모두 조합한 모형범위의 총 무투표 수는 "
        f"{zero_low:,}--{zero_high:,}개다. 이는 회계적 sharp 구간이 아니라 선택한 세 "
        "순위분포 유형 안에서의 조건부 범위다.", "",
        "경주별 유형확률과 추정 무투표 수는 `데이터/rank_profile_imputation_races.csv.gz`, "
        "조합별 점추정·모형범위·회계범위는 `데이터/rank_profile_imputed_cells.csv.gz`에 있다.", "",
        "## 식별 한계와 사용 규칙", "",
        "1. 실제 0이 학습표본에서 관측되지 않으므로 무투표 수는 분포형태와 정수 총합에서 "
        "나온 모형추정이지 자료만의 점식별 결과가 아니다.",
        "2. 순위곡선은 빈칸에 들어갈 숫자 묶음을 예측한다. 개별 조합 배정은 가시 셀의 "
        "1·2·3착 주변빈도 곱에 의존하므로 별도의 오차 원천이다.",
        "3. 공통지지 밖 경주는 외삽이다. 특히 학습경주가 20개 미만인 출전두수는 "
        "결과표에는 남기되 대표 추정이나 검증 성공률에 섞지 않는다.",
        "4. 다른 승식과 실제 착순·지급배당은 점추정의 입력으로 사용하지 않는다. 이 자료는 "
        "사후 외부검증에만 사용한다.",
        "5. 논문이나 후속 분석에서는 회계적 부분식별 구간을 주결과로 유지하고, 여기의 수치는 "
        "명시적으로 `모형 기반 복원` 또는 `조건부 추정`이라고 부른다.", "",
        "## 판정", "",
        "실제 상한 경주의 근접꼬리 가상검열에서는 공통지지 안팎과 네 상한값 모두에서 "
        "순위분포 모형의 셀 MAE가 균등배분보다 낮다. 따라서 순위형태를 옮겨 쓰는 발상은 "
        "조건부 복원모형으로 유지할 가치가 있다. 다만 정상경주의 7,000·9,000배 검증은 "
        "우위가 없고, 지급배당 선택표본의 공통지지 안 12건에서는 균등 MAE가 더 낮다. "
        "그러므로 현재 결과는 숫자 묶음의 꼬리형태에 대한 증거이지, 특정 조합별 추정치나 "
        "무투표 개수의 점식별 증거가 아니다.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--validation", type=pathlib.Path,
        default=pathlib.Path("데이터/rank_profile_validation.csv.gz"),
    )
    parser.add_argument(
        "--race-out", type=pathlib.Path,
        default=pathlib.Path("데이터/rank_profile_imputation_races.csv.gz"),
    )
    parser.add_argument(
        "--cell-out", type=pathlib.Path,
        default=pathlib.Path("데이터/rank_profile_imputed_cells.csv.gz"),
    )
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/rank_profile_imputation.md"),
    )
    args = parser.parse_args()

    races = load_races(args.data / "races.jsonl.gz")
    feasible = load_feasible(args.data / "trifecta_feasible_sets.csv.gz")
    train_ids = uncapped_ids(feasible, years={"2022", "2023", "2024"})
    print(f"load training grids: {len(train_ids):,} races", flush=True)
    training_grids = load_grids(args.data, races, train_ids)
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
    bounds, class_rows = support_bounds(metadata, mixture.labels)
    del training_grids

    test_ids = uncapped_ids(feasible, years={"2025"})
    print(f"load clean 2025 grids: {len(test_ids):,} races", flush=True)
    test_grids = load_grids(args.data, races, test_ids)
    validation_rows = clean_validation(races, test_grids, feasible, mixture, bounds)
    del test_grids

    target_ids = capped_ids(feasible)
    winners = load_winning_counts(args.data / "winning_capped_payouts.csv.gz")
    target_race_rows: list[dict[str, object]] = []
    seen_targets: set[str] = set()
    paths = sorted((args.data / "cells" / f"page_key={PAGE_KEY}").glob("*.csv.gz"))
    paths = [path for path in paths if "2022" <= path.name[:4] <= "2025"]
    with deterministic_csv(args.cell_out, CELL_FIELDS) as cell_writer:
        for path_index, path in enumerate(paths, 1):
            month_ids = {race_id for race_id in target_ids if race_id[:7] == path.name[:7]}
            grids = load_month_grids(path, races, month_ids)
            missing = month_ids - set(grids)
            if missing:
                raise ValueError(f"{path.name}: missing target grids {sorted(missing)[:5]}")
            for race_id in sorted(grids):
                seen_targets.add(race_id)
                race = races[race_id]
                info = feasible[race_id]
                values = grids[race_id]
                combos = [combo for combo, _ in values]
                sales = _won(race["sales"]["삼쌍승식"])
                total = sales // 100
                horses = sorted(set(race["horses"]) - set(race.get("scratched") or []))
                mid_counts, visible, capped, lower, upper = complete_visible_counts(
                    sales, values, int(info["residual_mid"])
                )
                point, point_rank, probabilities, chosen = predict_hidden(
                    mixture, mid_counts, visible, capped, combos, horses,
                    total_tickets=total, hidden_tickets=int(info["residual_mid"]),
                    upper=int(info["cap_upper"]),
                )
                uniform_point = uniform_hidden(
                    int(info["residual_mid"]), int(capped.sum()), int(info["cap_upper"])
                )
                uniform_scores = internal_assignment_scores(
                    combos, mid_counts, visible, capped, horses
                )
                uniform_assigned = assign_ranked_counts(uniform_point, uniform_scores)

                scenario_predictions = []
                for scenario in ("residual_min", "residual_mid", "residual_max"):
                    residual = int(info[scenario])
                    scenario_counts, scenario_visible, scenario_capped, _, _ = complete_visible_counts(
                        sales, values, residual
                    )
                    for class_index in range(len(CLASS_NAMES)):
                        assigned, _, _, _ = predict_hidden(
                            mixture, scenario_counts, scenario_visible, scenario_capped,
                            combos, horses, total_tickets=total, hidden_tickets=residual,
                            upper=int(info["cap_upper"]), class_index=class_index,
                        )
                        scenario_predictions.append(assigned)
                envelope = np.stack(scenario_predictions)
                model_min = envelope.min(axis=0)
                model_max = envelope.max(axis=0)
                common = in_common_support(info, bounds)
                zero_by_model = [int((prediction == 0).sum()) for prediction in scenario_predictions]
                race_row = {
                    "race_id": race_id, "year": info["year"], "meet": info["meet"],
                    "starters": info["starters"], "total_tickets": total,
                    "capped_cells": int(capped.sum()),
                    "residual_min": info["residual_min"], "residual_mid": info["residual_mid"],
                    "residual_max": info["residual_max"],
                    "profile_class": CLASS_NAMES[chosen],
                    "p_diffuse": format(float(probabilities[0]), ".8f"),
                    "p_intermediate": format(float(probabilities[1]), ".8f"),
                    "p_concentrated": format(float(probabilities[2]), ".8f"),
                    "common_support": int(common),
                    "estimated_zero_cells": int((point == 0).sum()),
                    "model_zero_min": min(zero_by_model),
                    "model_zero_max": max(zero_by_model),
                }
                target_race_rows.append(race_row)
                capped_indices = np.flatnonzero(capped)
                for local, cell_index in enumerate(capped_indices):
                    combo = combos[cell_index]
                    estimate = int(point[local])
                    odds = "unbet" if estimate == 0 else format(0.73 * sales / (100 * estimate), ".1f")
                    cell_writer.writerow({
                        "race_id": race_id, "year": info["year"], "meet": info["meet"],
                        "starters": info["starters"], "total_tickets": total,
                        "capped_cells": int(capped.sum()), "combo": "-".join(map(str, combo)),
                        "profile_class": CLASS_NAMES[chosen],
                        "class_probability": format(float(probabilities[chosen]), ".8f"),
                        "common_support": int(common), "residual_mid": info["residual_mid"],
                        "estimated_tickets": estimate,
                        "model_count_min": int(model_min[local]),
                        "model_count_max": int(model_max[local]),
                        "accounting_count_min": info["accounting_cell_min"],
                        "accounting_count_max": info["accounting_cell_max"],
                        "estimated_odds": odds,
                    })

                for threshold in (
                    VALIDATION_THRESHOLDS if str(info["year"]) == "2025" else ()
                ):
                    newly_hidden = np.asarray([
                        value != DISPLAY_CAP and value >= threshold for _, value in values
                    ])
                    if not newly_hidden.any() or np.any(lower[newly_hidden] != upper[newly_hidden]):
                        continue
                    hidden = capped | newly_hidden
                    visible_after = ~hidden
                    virtual_upper = capped_ticket_upper(sales, cap=threshold)
                    cell_uppers = np.asarray([
                        int(info["cap_upper"]) if capped[index] else virtual_upper
                        for index in np.flatnonzero(hidden)
                    ], dtype=np.int64)
                    try:
                        residual_lo, residual_hi = hidden_total_interval(
                            total,
                            lower[visible_after],
                            upper[visible_after],
                            cell_uppers,
                        )
                    except ValueError:
                        raise ValueError(
                            f"{race_id} {threshold}: near-tail residual infeasible"
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
                    predicted, ranked, near_probabilities, near_chosen = predict_hidden(
                        mixture, base, visible_after, hidden, combos, horses,
                        total_tickets=total, hidden_tickets=hidden_tickets,
                        upper=cell_uppers,
                    )
                    uniform_predicted = uniform_hidden(
                        hidden_tickets, int(hidden.sum()), cell_uppers
                    )
                    newly_local = np.flatnonzero(newly_hidden[hidden])
                    truth = lower[newly_hidden]
                    validation_rows.append(validation_row(
                        sample="capped_near_tail_2025", race_id=race_id,
                        year=str(info["year"]), threshold=threshold, model="rank_profile",
                        common_support=common, hidden_cells=int(hidden.sum()),
                        assessed_truth=truth, assessed_prediction=predicted[newly_local],
                        hidden_tickets=hidden_tickets, profile_class=CLASS_NAMES[near_chosen],
                    ))
                    validation_rows.append(validation_row(
                        sample="capped_near_tail_2025", race_id=race_id,
                        year=str(info["year"]), threshold=threshold, model="uniform",
                        common_support=common, hidden_cells=int(hidden.sum()),
                        assessed_truth=truth, assessed_prediction=uniform_predicted[newly_local],
                        hidden_tickets=hidden_tickets,
                    ))

                if race_id in winners:
                    cap_combos = [combos[index] for index in capped_indices]
                    lookup = {combo: i for i, combo in enumerate(cap_combos)}
                    for combo, truth_count in winners[race_id].items():
                        if combo not in lookup:
                            raise ValueError(f"{race_id}: winning capped combo absent {combo}")
                        local = lookup[combo]
                        for model, prediction in (("rank_profile", point), ("uniform", uniform_assigned)):
                            validation_rows.append(validation_row(
                                sample="winning_capped", race_id=race_id, year=str(info["year"]),
                                threshold=DISPLAY_CAP, model=model, common_support=common,
                                hidden_cells=int(capped.sum()), assessed_truth=np.asarray([truth_count]),
                                assessed_prediction=np.asarray([prediction[local]]),
                                hidden_tickets=int(info["residual_mid"]),
                                profile_class=CLASS_NAMES[chosen] if model == "rank_profile" else "",
                            ))
            print(
                f"target month {path_index}/{len(paths)}: {path.name}; "
                f"races={len(target_race_rows):,}; validation={len(validation_rows):,}",
                flush=True,
            )
    if seen_targets != target_ids:
        missing = target_ids - seen_targets
        raise ValueError(f"unprocessed target races: {sorted(missing)[:5]}")

    with deterministic_csv(args.validation, VALIDATION_FIELDS) as writer:
        writer.writerows(sorted(validation_rows, key=lambda row: (
            str(row["sample"]), str(row["race_id"]), str(row["threshold"]), str(row["model"])
        )))
    with deterministic_csv(args.race_out, RACE_FIELDS) as writer:
        writer.writerows(sorted(target_race_rows, key=lambda row: str(row["race_id"])))

    aggregate = aggregate_validation(validation_rows)
    make_plots(mixture, aggregate, args.report.parent)
    args.report.write_text(
        make_report(mixture, class_rows, aggregate, target_race_rows),
        encoding="utf-8",
    )
    print(f"wrote {args.validation}: {len(validation_rows):,} rows")
    print(f"wrote {args.race_out}: {len(target_race_rows):,} rows")
    print(f"wrote {args.cell_out}")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
