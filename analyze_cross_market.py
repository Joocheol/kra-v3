#!/usr/bin/env python3
"""Reconstruct lower-order market prices by marginalizing trifecta tickets."""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import io
import itertools
import math
import pathlib
import statistics
import tempfile
from decimal import Decimal

import numpy as np

from analyze_masked_reconstruction import bounded_integer_projection
from check_coherence import load_month, norm, spearman
from kra.feasible import displayed_ticket_interval


SCENARIOS = ("residual_min", "residual_mid", "residual_max")
TARGETS = ("win", "exacta", "quinella", "trio")
FIELDS = [
    "race_id", "year", "scenario", "target", "model", "cells",
    "squared_error_sum", "uniform_tss", "total_variation", "spearman",
]


def _won(value: object) -> int:
    digits = "".join(c for c in str(value) if c.isdigit())
    if not digits:
        raise ValueError(f"missing won amount: {value!r}")
    return int(digits)


def load_race_records(path: pathlib.Path) -> dict[str, dict]:
    import json
    rows = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            race = json.loads(line)
            if "2022" <= race["date"][:4] <= "2025":
                rows[race["race_id"]] = race
    return rows


def load_feasible(path: pathlib.Path) -> dict[str, dict[str, int]]:
    rows = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not ("2022" <= row["year"] <= "2025" and row["strict_feasible"] == "1"):
                continue
            lo = int(row["feasible_residual_min"])
            hi = int(row["feasible_residual_max"])
            rows[row["race_id"]] = {
                "residual_min": lo,
                "residual_mid": (lo + hi) // 2,
                "residual_max": hi,
                "cap_upper": int(row["cap_ticket_upper"]),
            }
    return rows


def completed_trifecta(
    race: dict,
    odds: dict[tuple[int, int, int], float],
    feasible: dict[str, int],
    scenario: str,
    *,
    allocation: str = "uniform",
    beta: float = 0.0,
) -> dict[tuple[int, int, int], float]:
    sales = _won(race["sales"]["삼쌍승식"])
    total = sales // 100
    uncapped, capped = [], []
    lower, upper, target = [], [], []
    for combo, value in sorted(odds.items()):
        if value == 9999.9:
            capped.append(combo)
            continue
        candidates = displayed_ticket_interval(sales, Decimal(str(value)))
        if not candidates:
            raise ValueError(f"{race['race_id']}: incompatible trifecta {combo}={value}")
        uncapped.append(combo)
        lower.append(candidates.start)
        upper.append(candidates.stop - 1)
        target.append(.73 * total / value)
    residual = feasible[scenario]
    uncapped_total = total - residual
    uncapped_counts = bounded_integer_projection(
        np.asarray(target), np.asarray(lower), np.asarray(upper), uncapped_total
    )
    scores = np.ones(len(capped), dtype=float)
    if allocation == "position_independent":
        if capped:
            horses = sorted({horse for combo in odds for horse in combo})
            horse_index = {horse: index for index, horse in enumerate(horses)}
            marginals = [np.full(len(horses), .5) for _ in range(3)]
            for combo, count in zip(uncapped, uncapped_counts):
                for position, horse in enumerate(combo):
                    marginals[position][horse_index[horse]] += float(count)
            scores = np.asarray([
                marginals[0][horse_index[a]]
                * marginals[1][horse_index[b]]
                * marginals[2][horse_index[c]]
                for a, b, c in capped
            ])
    elif allocation != "uniform":
        raise ValueError(f"unknown capped allocation: {allocation}")
    if capped:
        tempered = np.power(scores, beta)
        probabilities = tempered / tempered.sum()
        capped_counts = bounded_integer_projection(
            residual * probabilities,
            np.zeros(len(capped), dtype=np.int64),
            np.full(len(capped), feasible["cap_upper"], dtype=np.int64),
            residual,
        )
    else:
        capped_counts = np.asarray([], dtype=np.int64)
    if capped_counts.size and int(capped_counts.max()) > feasible["cap_upper"]:
        raise ValueError(f"{race['race_id']}: {allocation} completion exceeds cap upper")
    counts = {
        combo: float(count) / total
        for combo, count in zip(uncapped, uncapped_counts)
    }
    counts.update(
        (combo, float(count) / total) for combo, count in zip(capped, capped_counts)
    )
    if not math.isclose(sum(counts.values()), 1.0, abs_tol=1e-12):
        raise AssertionError(f"{race['race_id']}: completed shares do not sum to one")
    return counts


def marginalize(
    trifecta: dict[tuple[int, int, int], float]
) -> dict[str, dict[object, float]]:
    out = {target: collections.Counter() for target in TARGETS}
    for (a, b, c), probability in trifecta.items():
        out["win"][a] += probability
        out["exacta"][(a, b)] += probability
        out["quinella"][frozenset((a, b))] += probability
        out["trio"][frozenset((a, b, c))] += probability
    return {key: dict(value) for key, value in out.items()}


def harville(win_odds: dict[int, float]) -> dict[str, dict[object, float]]:
    p = norm({horse: 1 / value for horse, value in win_odds.items()})
    triples = {}
    for a, b, c in itertools.permutations(sorted(p), 3):
        triples[(a, b, c)] = p[a] * p[b] / (1 - p[a]) * p[c] / (1 - p[a] - p[b])
    total = sum(triples.values())
    triples = {key: value / total for key, value in triples.items()}
    return marginalize(triples)


def target_probabilities(pool: dict[object, float]) -> dict[object, float] | None:
    if not pool or any(value == 9999.9 for value in pool.values()):
        return None
    return norm({key: 1 / value for key, value in pool.items()})


def metric_row(
    race_id: str, year: str, scenario: str, target: str, model: str,
    truth: dict[object, float], prediction: dict[object, float],
) -> dict[str, object] | None:
    if set(truth) != set(prediction) or len(truth) < 2:
        return None
    keys = sorted(truth, key=str)
    y = [truth[key] for key in keys]
    pred = [prediction[key] for key in keys]
    uniform = 1 / len(keys)
    return {
        "race_id": race_id,
        "year": year,
        "scenario": scenario,
        "target": target,
        "model": model,
        "cells": len(keys),
        "squared_error_sum": format(
            sum((a - b) ** 2 for a, b in zip(y, pred)), ".12g"
        ),
        "uniform_tss": format(sum((a - uniform) ** 2 for a in y), ".12g"),
        "total_variation": format(
            .5 * sum(abs(a - b) for a, b in zip(y, pred)), ".12g"
        ),
        "spearman": format(spearman(y, pred), ".12g"),
    }


def write_csv_gz(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
        tmp = pathlib.Path(raw.name)
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=FIELDS, lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
    tmp.replace(path)


def make_report(rows: list[dict[str, object]]) -> str:
    lines = [
        "# 삼쌍승 가격의 하위 승식 재구성", "", "## 설계", "",
        "2022--2025년 삼쌍승 배당을 100원 마권수로 복원하고 상위 1·2·3착 "
        "상태분포로 정규화했다. `9999.9` 셀의 경주별 잔여총량은 회계적 하한·"
        "중간값·상한을 각각 사용하고, 셀 사이에는 최소 대칭 기준선인 균등배분을 "
        "적용했다. 이를 주변화해 단승·쌍승·복승·삼복승의 실제 "
        "정규화 역배당과 비교한다. 단승 Harville 순차모형을 공통 기준선으로 둔다.", "",
        "`R²`의 분모는 경주별 균등가격을 기준으로 한 편차제곱합이다. 따라서 0은 "
        "균등분포와 같고 1은 대상 시장을 정확히 재구성한다. 대상 승식 자체가 "
        "`9999.9`인 경주는 정답이 검열되어 제외한다.", "",
        "## 2025년 주결과 (`R` 중간값)", "",
        "| 대상 | 모형 | 경주 | 셀 | R² | 평균 TV 거리 | Spearman 중앙값 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    def append(period: str, scenario: str, target: str, model: str) -> None:
        group = [
            row for row in rows
            if row["scenario"] == scenario and row["target"] == target
            and row["model"] == model
            and (row["year"] == "2025" if period == "2025" else row["year"] <= "2024")
        ]
        if not group:
            return
        sse = sum(float(row["squared_error_sum"]) for row in group)
        tss = sum(float(row["uniform_tss"]) for row in group)
        tv = statistics.mean(float(row["total_variation"]) for row in group)
        cor = statistics.median(float(row["spearman"]) for row in group)
        cells = sum(int(row["cells"]) for row in group)
        lines.append(
            f"| {target} | {model} | {len(group):,} | {cells:,} | "
            f"{1-sse/tss:.5f} | {tv:.5f} | {cor:.5f} |"
        )
    for target in TARGETS:
        append("2025", "residual_mid", target, "trifecta_uniform")
        append("2025", "residual_mid", target, "trifecta_position_beta_010")
        append("2025", "residual_mid", target, "trifecta_swapped_23")
        if target != "win":
            append("2025", "residual_mid", target, "win_harville")
    lines.extend([
        "", "## 검열 잔여총량 민감도: 삼쌍승 주변화의 2025년 R²", "",
        "| 대상 | R 하한 | R 중간값 | R 상한 |", "| --- | ---: | ---: | ---: |",
    ])
    for target in TARGETS:
        values = []
        for scenario in SCENARIOS:
            group = [
                row for row in rows if row["year"] == "2025"
                and row["scenario"] == scenario and row["target"] == target
                and row["model"] == "trifecta_uniform"
            ]
            sse = sum(float(row["squared_error_sum"]) for row in group)
            tss = sum(float(row["uniform_tss"]) for row in group)
            values.append(1 - sse / tss)
        lines.append(f"| {target} | {values[0]:.5f} | {values[1]:.5f} | {values[2]:.5f} |")
    lines.extend([
        "", "## 해석 경계", "",
        "이 결과는 서로 다른 풀의 가격 내부 정합성을 측정한다. 실제 착순을 쓰지 "
        "않으므로 객관적 예측력·시장효율성·인과효과를 뜻하지 않는다. `R` 시나리오 "
        "차이가 작은 것은 균등배분을 고정한 조건부 결과다. "
        "`trifecta_position_beta_010`은 가상 상한에서 함께 지지된 비균등 대안에 대한 "
        "배분 민감도이고, `trifecta_swapped_23`은 2·3착 축을 뒤집은 반증모형이다. "
        "후자가 쌍승·복승에서 악화되는지는 축 방향의 내부 가격정보를 검사하지만 "
        "외부 진실을 검증하지는 않는다. 경주별 수치는 "
        "`데이터/cross_market_reconstruction.csv.gz`에 있다.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--out", type=pathlib.Path,
        default=pathlib.Path("데이터/cross_market_reconstruction.csv.gz"),
    )
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/cross_market_reconstruction.md"),
    )
    args = parser.parse_args()
    records = load_race_records(args.data / "races.jsonl.gz")
    feasible = load_feasible(args.data / "trifecta_feasible_sets.csv.gz")
    rows = []
    months = sorted({race["date"][:7] for race in records.values()})
    for index, month in enumerate(months, 1):
        print(f"cross market {index}/{len(months)}: {month}", flush=True)
        markets = load_month(args.data, month)
        for race_id, market in markets.items():
            race = records.get(race_id)
            info = feasible.get(race_id)
            if race is None or info is None or not market["trifecta"]:
                continue
            targets = {
                "win": target_probabilities(market["win"]),
                "exacta": target_probabilities(market["exacta"]),
                "quinella": target_probabilities(market["quinella"]),
                "trio": target_probabilities(market["trio"]),
            }
            baseline = harville(market["win"])
            for scenario in SCENARIOS:
                completed = completed_trifecta(
                    race, market["trifecta"], info, scenario
                )
                projected = marginalize(completed)
                alternatives = []
                if scenario == "residual_mid":
                    position = completed_trifecta(
                        race, market["trifecta"], info, scenario,
                        allocation="position_independent", beta=.10,
                    )
                    alternatives = [
                        ("trifecta_position_beta_010", marginalize(position)),
                        (
                            "trifecta_swapped_23",
                            marginalize({
                                (a, c, b): probability
                                for (a, b, c), probability in completed.items()
                            }),
                        ),
                    ]
                for target in TARGETS:
                    truth = targets[target]
                    if truth is None:
                        continue
                    row = metric_row(
                        race_id, race["date"][:4], scenario, target,
                        "trifecta_uniform", truth, projected[target]
                    )
                    if row: rows.append(row)
                    for model, alternative in alternatives:
                        row = metric_row(
                            race_id, race["date"][:4], scenario, target,
                            model, truth, alternative[target]
                        )
                        if row: rows.append(row)
                    if scenario == "residual_mid" and target != "win":
                        row = metric_row(
                            race_id, race["date"][:4], scenario, target,
                            "win_harville", truth, baseline[target]
                        )
                        if row: rows.append(row)
    write_csv_gz(args.out, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(make_report(rows), encoding="utf-8")
    print(f"wrote {args.out}: {len(rows):,} rows")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
