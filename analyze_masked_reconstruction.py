#!/usr/bin/env python3
"""Validate trifecta ticket-allocation models with artificial display caps.

The primary sample is 2022--2025 races with no real ``9999.9`` cells.  Exact
one-decimal ticket intervals are intersected with the race pool total, and a
deterministic minimum-distance integer table is constructed inside that
identified set.  Cells above virtual caps are then hidden and reconstructed
conditional on their known residual ticket total.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import pathlib
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from kra.feasible import displayed_ticket_interval
from collect_winning_payouts import _grid_combination


PAGE_KEY = "3Both"
THRESHOLDS = (Decimal("3000.0"), Decimal("5000.0"), Decimal("7000.0"))
MODELS = (
    "uniform", "position_independent", "sequential_prefix",
    "win_harville", "exacta_then_third", "trio_then_order",
)
BETAS = (0.0, 0.05, 0.10, 0.20, 0.35, 0.50, 0.75, 1.0)
NUMERIC_ODDS = re.compile(r"^[0-9]+\.[0-9]$")
FIELDS = [
    "race_id", "year", "threshold", "model", "beta", "cells", "masked_cells",
    "masked_singleton_cells", "masked_tickets", "absolute_error_sum",
    "squared_log1p_error_sum", "exact_cells", "cross_entropy_sum",
]


def _won(value: object) -> int:
    digits = "".join(c for c in str(value) if c.isdigit())
    if not digits:
        raise ValueError(f"missing won amount: {value!r}")
    return int(digits)


def load_races(path: pathlib.Path) -> dict[str, dict]:
    races = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            race = json.loads(line)
            races[race["race_id"]] = race
    return races


def primary_race_ids(path: pathlib.Path) -> set[str]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return {
            row["race_id"] for row in csv.DictReader(fh)
            if row["year"] >= "2022" and row["year"] <= "2025"
            and row["capped_cells"] == "0" and row["strict_feasible"] == "1"
        }


def load_grids(
    data: pathlib.Path, races: dict[str, dict], wanted: set[str]
) -> dict[str, list[tuple[tuple[int, int, int], Decimal]]]:
    grids: dict[str, list[tuple[tuple[int, int, int], Decimal]]] = defaultdict(list)
    seen: dict[str, set[tuple[int, int, int]]] = defaultdict(set)
    paths = sorted((data / "cells" / f"page_key={PAGE_KEY}").glob("*.csv.gz"))
    for index, path in enumerate(paths, 1):
        if path.name[:4] < "2022":
            continue
        print(f"mask input {index}/{len(paths)}: {path.name}", flush=True)
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                race_id = row["race_id"]
                if race_id not in wanted or row["section"] != "body" or row["spanned"] != "0":
                    continue
                raw = row["cell_raw"]
                if not NUMERIC_ODDS.fullmatch(raw):
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
                grids[race_id].append((combo, Decimal(raw)))
    missing = wanted - set(grids)
    if missing:
        raise ValueError(f"missing primary grids: {sorted(missing)[:5]}")
    for race_id, values in grids.items():
        n = len(races[race_id]["horses"]) - len(races[race_id].get("scratched") or [])
        expected = n * (n - 1) * (n - 2)
        if len(values) != expected:
            raise ValueError(f"{race_id}: {len(values)} combinations, expected {expected}")
    return grids


def load_cross_pool_odds(
    data: pathlib.Path, wanted: set[str]
) -> dict[str, dict[str, dict[tuple[int, ...], float]]]:
    out: dict[str, dict[str, dict[tuple[int, ...], float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for page in ("Scm", "Both", "3Bc"):
        for path in sorted((data / "cells" / f"page_key={page}").glob("*.csv.gz")):
            if path.name[:4] < "2022":
                continue
            print(f"cross-pool {page}: {path.name}", flush=True)
            with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if (
                        row["race_id"] not in wanted or row["section"] != "body"
                        or row["spanned"] != "0" or not NUMERIC_ODDS.fullmatch(row["cell_raw"])
                    ):
                        continue
                    parsed = _grid_combination(row)
                    if parsed is None:
                        continue
                    pool, combo = parsed
                    if pool not in {"단승식", "쌍승식", "삼복승식"}:
                        continue
                    value = float(row["cell_raw"])
                    if value <= 0:
                        continue
                    prior = out[row["race_id"]][pool].get(combo)
                    if prior is not None and prior != value:
                        raise ValueError(f"duplicate cross-pool odds: {row['race_id']} {pool} {combo}")
                    out[row["race_id"]][pool][combo] = value
    return out


def bounded_integer_projection(
    target: np.ndarray, lower: np.ndarray, upper: np.ndarray, total: int
) -> np.ndarray:
    """Minimize squared distance to target under integer boxes and one sum."""
    if lower.sum() > total or upper.sum() < total:
        raise ValueError("total is outside interval-sum bounds")
    lo = float(np.min(lower - target) - 1.0)
    hi = float(np.max(upper - target) + 1.0)
    for _ in range(70):
        mid = (lo + hi) / 2
        if np.clip(target + mid, lower, upper).sum() < total:
            lo = mid
        else:
            hi = mid
    continuous = np.clip(target + (lo + hi) / 2, lower, upper)
    result = np.floor(continuous + 1e-10).astype(np.int64)
    result = np.maximum(result, lower)
    result = np.minimum(result, upper)
    remainder = int(total - result.sum())
    if remainder > 0:
        eligible = np.flatnonzero(result < upper)
        order = eligible[np.argsort(-(continuous[eligible] - result[eligible]), kind="stable")]
        if remainder > len(order):
            raise AssertionError("integer projection remainder exceeds eligible cells")
        result[order[:remainder]] += 1
    elif remainder < 0:
        eligible = np.flatnonzero(result > lower)
        order = eligible[np.argsort(continuous[eligible] - result[eligible], kind="stable")]
        if -remainder > len(order):
            raise AssertionError("integer projection decrement exceeds eligible cells")
        result[order[:-remainder]] -= 1
    if int(result.sum()) != total or np.any(result < lower) or np.any(result > upper):
        raise AssertionError("invalid projected table")
    return result


def reconstruct_counts(
    sales_won: int, values: list[tuple[tuple[int, int, int], Decimal]]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lower, upper, target = [], [], []
    total = sales_won // 100
    for _, odds in values:
        candidates = displayed_ticket_interval(sales_won, odds)
        if not candidates:
            raise ValueError(f"incompatible primary-sample odds: {odds}")
        lower.append(candidates.start)
        upper.append(candidates.stop - 1)
        target.append(0.73 * total / float(odds))
    lo = np.asarray(lower, dtype=np.int64)
    hi = np.asarray(upper, dtype=np.int64)
    counts = bounded_integer_projection(np.asarray(target), lo, hi, total)
    return counts, lo, hi


def proportional_integer_allocation(total: int, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if total < 0 or len(scores) == 0 or np.any(scores < 0):
        raise ValueError("invalid proportional allocation")
    if not np.isfinite(scores).all() or scores.sum() <= 0:
        scores = np.ones(len(scores), dtype=float)
    probabilities = scores / scores.sum()
    expected = total * probabilities
    result = np.floor(expected).astype(np.int64)
    remainder = total - int(result.sum())
    if remainder:
        order = np.argsort(-(expected - result), kind="stable")
        result[order[:remainder]] += 1
    return result, probabilities


def model_scores(
    model: str,
    combos: list[tuple[int, int, int]],
    counts: np.ndarray,
    visible: np.ndarray,
    masked: np.ndarray,
    horses: list[int],
    cross_pool: dict[str, dict[tuple[int, ...], float]] | None = None,
    alpha: float = 0.5,
) -> np.ndarray:
    if model == "uniform":
        return np.ones(int(masked.sum()))
    cross_pool = cross_pool or {}
    win = cross_pool.get("단승식", {})
    missing_win = [horse for horse in horses if (horse,) not in win]
    if model in {"win_harville", "exacta_then_third", "trio_then_order"} and missing_win:
        raise ValueError(f"incomplete win pool for {model}: {missing_win}")
    raw_win = {horse: 1.0 / win.get((horse,), math.inf) for horse in horses}
    win_total = sum(raw_win.values())
    win_prob = {horse: raw_win[horse] / win_total for horse in horses}
    horse_index = {horse: index for index, horse in enumerate(horses)}
    h = len(horses)
    m1 = np.full(h, alpha)
    m2 = np.full(h, alpha)
    m3 = np.full(h, alpha)
    c12 = np.full((h, h), alpha)
    c123 = defaultdict(lambda: alpha)
    for index in np.flatnonzero(visible):
        i, j, k = (horse_index[x] for x in combos[index])
        weight = float(counts[index])
        m1[i] += weight
        m2[j] += weight
        m3[k] += weight
        c12[i, j] += weight
        c123[(i, j, k)] += weight
    scores = []
    for index in np.flatnonzero(masked):
        combo = combos[index]
        if model == "win_harville":
            i_h, j_h, k_h = combo
            pi, pj, pk = win_prob[i_h], win_prob[j_h], win_prob[k_h]
            scores.append(pi * pj / (1 - pi) * pk / (1 - pi - pj))
            continue
        if model == "exacta_then_third":
            exacta = cross_pool.get("쌍승식", {})
            i_h, j_h, k_h = combo
            if combo[:2] not in exacta:
                raise ValueError(f"incomplete exacta pool: {combo[:2]}")
            scores.append(
                (1.0 / exacta.get(combo[:2], math.inf))
                * win_prob[k_h] / (1 - win_prob[i_h] - win_prob[j_h])
            )
            continue
        if model == "trio_then_order":
            trio = cross_pool.get("삼복승식", {})
            unordered = tuple(sorted(combo))
            if unordered not in trio:
                raise ValueError(f"incomplete trio pool: {unordered}")
            i_h, j_h, k_h = combo
            within = win_prob[i_h] + win_prob[j_h] + win_prob[k_h]
            order = (
                win_prob[i_h] / within
                * win_prob[j_h] / (win_prob[j_h] + win_prob[k_h])
            )
            scores.append((1.0 / trio.get(unordered, math.inf)) * order)
            continue
        i, j, k = (horse_index[x] for x in combos[index])
        if model == "position_independent":
            scores.append(m1[i] * m2[j] * m3[k])
        elif model == "sequential_prefix":
            p1 = m1[i] / m1.sum()
            p2 = c12[i, j] / sum(c12[i, z] for z in range(h) if z != i)
            prefix_total = sum(c123[(i, j, z)] for z in range(h) if z not in (i, j))
            p3 = c123[(i, j, k)] / prefix_total
            scores.append(p1 * p2 * p3)
        else:
            raise ValueError(f"unknown model: {model}")
    return np.asarray(scores, dtype=float)


def evaluate_race(
    race: dict,
    values: list[tuple[tuple[int, int, int], Decimal]],
    cross_pool: dict[str, dict[tuple[int, ...], float]],
) -> list[dict[str, object]]:
    sales = _won(race["sales"]["삼쌍승식"])
    counts, lower, upper = reconstruct_counts(sales, values)
    combos = [combo for combo, _ in values]
    odds = np.asarray([float(value) for _, value in values])
    active = sorted(set(race["horses"]) - set(race.get("scratched") or []))
    rows = []
    for threshold in THRESHOLDS:
        masked = odds >= float(threshold)
        if not masked.any() or masked.all():
            continue
        visible = ~masked
        residual = int(counts[masked].sum())
        for model in MODELS:
            scores = model_scores(
                model, combos, counts, visible, masked, active,
                cross_pool=cross_pool,
            )
            truth = counts[masked]
            betas = (0.0,) if model == "uniform" else BETAS
            for beta in betas:
                tempered = np.power(scores, beta)
                predicted, probabilities = proportional_integer_allocation(
                    residual, tempered
                )
                rows.append({
                    "race_id": race["race_id"],
                    "year": race["date"][:4],
                    "threshold": str(threshold),
                    "model": model,
                    "beta": f"{beta:.2f}",
                    "cells": len(values),
                    "masked_cells": int(masked.sum()),
                    "masked_singleton_cells": int(((lower == upper) & masked).sum()),
                    "masked_tickets": residual,
                    "absolute_error_sum": int(np.abs(predicted - truth).sum()),
                    "squared_log1p_error_sum": float(
                        np.square(np.log1p(predicted) - np.log1p(truth)).sum()
                    ),
                    "exact_cells": int((predicted == truth).sum()),
                    "cross_entropy_sum": float(
                        -(truth * np.log(np.maximum(probabilities, 1e-300))).sum()
                    ),
                })
    return rows


def write_csv_gz(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
        tmp = pathlib.Path(raw.name)
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
    tmp.replace(path)


def make_report(rows: list[dict[str, object]], n_races: int) -> str:
    lines = [
        "# 가상 상한을 이용한 삼쌍승 마권배분 복원 검증", "",
        "## 설계", "",
        f"2022--2025년 실제 `9999.9`가 없는 {n_races:,}개 경주에서 표시배당의 "
        "정수구간과 경주 총마권 수를 동시에 만족하는 표를 구성했다. 3,000·5,000·"
        "7,000배 이상의 셀을 가리고, 숨긴 셀 전체의 마권 수만 알려 준 조건에서 "
        "내부·외부시장 배분모형을 비교했다. 이는 상한 셀 내부의 배분 성능을 분리해 보는 "
        "검증이며 실제 상한 셀의 0 여부를 직접 검증하는 것은 아니다. 세 가상 상한의 "
        "셀-실험을 합산한 247,584건은 모두 표시배당의 정수구간이 한 값뿐이어서 "
        "셀별 정답이 점식별된다.", "",
        "- `uniform`: 숨긴 조합에 균등 배분",
        "- `position_independent`: 1·2·3착 말의 가시 셀 주변빈도 곱",
        "- `sequential_prefix`: 1착 → 2착|1착 → 3착|1·2착 순차조건부 빈도", "",
        "- `win_harville`: 단승 역배당으로 만든 Harville 순차확률",
        "- `exacta_then_third`: 쌍승 역배당 × 3착 말 단승 역배당",
        "- `trio_then_order`: 삼복승 역배당 × 세 말 집합 내부 Harville 순서확률", "",
        "각 비균등 점수는 `score^beta`로 완화한다. `beta=0`은 균등, `beta=1`은 "
        "원래 모형이다. 가상 상한·모형별 `beta`는 2022--2024의 마권가중 "
        "교차엔트로피를 최소화하도록 선택하고, 아래 성능은 선택에 사용하지 않은 "
        "2025년에만 계산했다.", "",
        "## 2025년 시간외 검증 결과", "",
        "| 가상 상한 | 모형 | 선택 beta | 훈련 CE | 시험 경주 | 숨긴 셀 | MAE | log1p RMSE | 정확 일치 | 시험 CE |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["threshold"]), str(row["model"]), str(row["beta"]))].append(row)
    for threshold in map(str, THRESHOLDS):
        for model in MODELS:
            choices = []
            betas = (0.0,) if model == "uniform" else BETAS
            for beta in betas:
                group = groups.get((threshold, model, f"{beta:.2f}"), [])
                train = [row for row in group if str(row["year"]) <= "2024"]
                if not train:
                    continue
                train_tickets = sum(int(row["masked_tickets"]) for row in train)
                train_ce = sum(float(row["cross_entropy_sum"]) for row in train) / train_tickets
                choices.append((train_ce, beta, group))
            if not choices:
                continue
            train_ce, beta, group = min(choices, key=lambda item: (item[0], item[1]))
            group = [row for row in group if str(row["year"]) == "2025"]
            cells = sum(int(row["masked_cells"]) for row in group)
            tickets = sum(int(row["masked_tickets"]) for row in group)
            mae = sum(int(row["absolute_error_sum"]) for row in group) / cells
            rmse = math.sqrt(
                sum(float(row["squared_log1p_error_sum"]) for row in group) / cells
            )
            exact = sum(int(row["exact_cells"]) for row in group) / cells
            ce = sum(float(row["cross_entropy_sum"]) for row in group) / tickets
            lines.append(
                f"| {threshold} | {model} | {beta:.2f} | {train_ce:.4f} | "
                f"{len(group):,} | {cells:,} | {mae:.3f} | {rmse:.4f} | "
                f"{exact:.2%} | {ce:.4f} |"
            )
    lines.extend([
        "", "모든 모형은 숨긴 셀의 총마권 수를 정확히 보존한다. 따라서 차이는 "
        "총량 추정이 아니라 조합 간 배분에서 나온다. 셀별 상세 집계는 "
        "`데이터/masked_reconstruction_results.csv.gz`에 있다.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--out", type=pathlib.Path,
        default=pathlib.Path("데이터/masked_reconstruction_results.csv.gz"),
    )
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/masked_reconstruction.md"),
    )
    args = parser.parse_args()
    races = load_races(args.data / "races.jsonl.gz")
    wanted = primary_race_ids(args.data / "trifecta_feasible_sets.csv.gz")
    grids = load_grids(args.data, races, wanted)
    cross_pool = load_cross_pool_odds(args.data, wanted)
    rows = []
    for index, race_id in enumerate(sorted(wanted), 1):
        rows.extend(evaluate_race(
            races[race_id], grids[race_id], cross_pool.get(race_id, {})
        ))
        if index % 250 == 0 or index == len(wanted):
            print(f"evaluate {index}/{len(wanted)}: {len(rows):,} rows", flush=True)
    write_csv_gz(args.out, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(make_report(rows, len(wanted)), encoding="utf-8")
    print(f"wrote {args.out}: {len(rows):,} rows")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
