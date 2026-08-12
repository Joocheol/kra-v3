#!/usr/bin/env python3
"""Fit symmetric Dirichlet--multinomial overdispersion on virtual caps."""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import math
import pathlib
import tempfile

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import betaln, gammaln

from analyze_masked_reconstruction import (
    THRESHOLDS,
    _won,
    load_grids,
    load_races,
    primary_race_ids,
    reconstruct_counts,
)


SUMMARY_FIELDS = [
    "threshold", "alpha", "training_races", "training_cells", "training_tickets",
    "training_loglik_gain_per_cell", "test_races", "test_cells", "test_tickets",
    "test_loglik_gain_per_cell",
]
ACTUAL_FIELDS = [
    "race_id", "year", "capped_cells", "residual_min", "residual_mid",
    "residual_max", "alpha", "expected_zeros_residual_max",
    "expected_zeros_residual_mid", "expected_zeros_residual_min",
]


def multinomial_loglik(counts: np.ndarray) -> float:
    total = int(counts.sum())
    cells = len(counts)
    return float(gammaln(total + 1) - gammaln(counts + 1).sum() - total * math.log(cells))


def dm_loglik(counts: np.ndarray, alpha: float) -> float:
    total = int(counts.sum())
    cells = len(counts)
    return float(
        gammaln(total + 1) - gammaln(counts + 1).sum()
        + gammaln(cells * alpha) - gammaln(total + cells * alpha)
        + (gammaln(counts + alpha) - gammaln(alpha)).sum()
    )


def fit_alpha(vectors: list[np.ndarray]) -> float:
    def objective(log_alpha: float) -> float:
        alpha = math.exp(log_alpha)
        return -sum(dm_loglik(vector, alpha) for vector in vectors)
    result = minimize_scalar(objective, bounds=(-8.0, 15.0), method="bounded")
    if not result.success:
        raise RuntimeError(f"alpha optimization failed: {result.message}")
    return math.exp(float(result.x))


def zero_probability(cells: int, tickets: int, alpha: float) -> float:
    if tickets == 0:
        return 1.0
    if cells == 1:
        return 0.0
    return math.exp(
        betaln(alpha, (cells - 1) * alpha + tickets)
        - betaln(alpha, (cells - 1) * alpha)
    )


def virtual_vectors(
    races: dict[str, dict],
    grids: dict[str, list[tuple[tuple[int, int, int], object]]],
) -> dict[str, list[tuple[str, np.ndarray]]]:
    out = {str(threshold): [] for threshold in THRESHOLDS}
    for race_id in sorted(grids):
        values = grids[race_id]
        counts, _, _ = reconstruct_counts(
            _won(races[race_id]["sales"]["삼쌍승식"]), values
        )
        odds = np.asarray([float(value) for _, value in values])
        for threshold in THRESHOLDS:
            masked = odds >= float(threshold)
            if masked.any() and not masked.all():
                out[str(threshold)].append((races[race_id]["date"][:4], counts[masked]))
    return out


def summarize(vectors_by_threshold: dict[str, list[tuple[str, np.ndarray]]]) -> list[dict]:
    rows = []
    for threshold in map(str, THRESHOLDS):
        all_vectors = vectors_by_threshold[threshold]
        train = [vector for year, vector in all_vectors if year <= "2024"]
        test = [vector for year, vector in all_vectors if year == "2025"]
        alpha = float(format(fit_alpha(train), ".12g"))
        def stats(vectors: list[np.ndarray]) -> tuple[int, int, float]:
            cells = sum(len(vector) for vector in vectors)
            tickets = sum(int(vector.sum()) for vector in vectors)
            gain = sum(
                dm_loglik(vector, alpha) - multinomial_loglik(vector)
                for vector in vectors
            ) / cells
            return cells, tickets, gain
        train_cells, train_tickets, train_gain = stats(train)
        test_cells, test_tickets, test_gain = stats(test)
        rows.append({
            "threshold": threshold,
            "alpha": format(alpha, ".12g"),
            "training_races": len(train),
            "training_cells": train_cells,
            "training_tickets": train_tickets,
            "training_loglik_gain_per_cell": format(train_gain, ".12g"),
            "test_races": len(test),
            "test_cells": test_cells,
            "test_tickets": test_tickets,
            "test_loglik_gain_per_cell": format(test_gain, ".12g"),
        })
    return rows


def actual_rows(path: pathlib.Path, alpha: float) -> list[dict]:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not (
                "2022" <= row["year"] <= "2025"
                and int(row["capped_cells"]) > 0
                and row["strict_feasible"] == "1"
            ):
                continue
            cells = int(row["capped_cells"])
            lo = int(row["feasible_residual_min"])
            hi = int(row["feasible_residual_max"])
            mid = (lo + hi) // 2
            rows.append({
                "race_id": row["race_id"],
                "year": row["year"],
                "capped_cells": cells,
                "residual_min": lo,
                "residual_mid": mid,
                "residual_max": hi,
                "alpha": format(alpha, ".12g"),
                "expected_zeros_residual_max": format(
                    cells * zero_probability(cells, hi, alpha), ".12g"
                ),
                "expected_zeros_residual_mid": format(
                    cells * zero_probability(cells, mid, alpha), ".12g"
                ),
                "expected_zeros_residual_min": format(
                    cells * zero_probability(cells, lo, alpha), ".12g"
                ),
            })
    return rows


def write_csv(path: pathlib.Path, rows: list[dict], fields: list[str], *, zipped: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not zipped:
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
        tmp = pathlib.Path(raw.name)
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
    tmp.replace(path)


def report(summary: list[dict], actual: list[dict]) -> str:
    alpha = float(summary[-1]["alpha"])
    cells = sum(int(row["capped_cells"]) for row in actual)
    expected_low = sum(float(row["expected_zeros_residual_max"]) for row in actual)
    expected_mid = sum(float(row["expected_zeros_residual_mid"]) for row in actual)
    expected_high = sum(float(row["expected_zeros_residual_min"]) for row in actual)
    zero_lower_races = sum(int(row["residual_min"]) == 0 for row in actual)
    lines = [
        "# 선택표본의 Dirichlet--multinomial 과산포 진단", "", "## 추정과 시간외 검증", "",
        "실제 `9999.9`가 없는 경주에 3,000·5,000·7,000 가상 상한을 적용한 "
        "정확 마권수 벡터로 대칭 Dirichlet--multinomial의 셀별 농도 `alpha`를 "
        "2022--2024년에 추정하고 2025년에 평가했다. `alpha→∞`는 대칭 다항모형이다.", "",
        "| 가상 상한 | alpha | 훈련 경주 | 시험 경주 | 훈련 셀당 로그우도 개선 | 시험 셀당 개선 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary:
        lines.append(
            f"| {row['threshold']} | {float(row['alpha']):.3f} | "
            f"{int(row['training_races']):,} | {int(row['test_races']):,} | "
            f"{float(row['training_loglik_gain_per_cell']):.5f} | "
            f"{float(row['test_loglik_gain_per_cell']):.5f} |"
        )
    lines.extend([
        "", "## 실제 상한 셀에 대한 기능형식 외삽 (주결과 아님)", "",
        f"실제 상한에 가장 가까운 7,000배 추정치 `alpha={alpha:.3f}`를 사용했다. "
        "경주별 잔여총량 `R`의 회계적 식별구간은 그대로 전파했다. 그러나 적합표본은 "
        "엄격히 양수이고 가상 상한으로 선택된 벡터라 실제 상한 표본과 지원집합이 다르다. "
        "아래 값은 구조적 모수가 아니라 무조건부 DM 기능형식을 적용한 민감도다.", "",
        "| 항목 | 값 |", "| --- | ---: |",
        f"| 경주 | {len(actual):,} |",
        f"| 실제 `9999.9` 셀 | {cells:,} |",
        f"| 과산포모형 기대 무투표 (`R` 중간값) | {expected_mid:.3e} "
        f"({100*expected_mid/cells:.3e}%) |",
        f"| `R` 식별구간 전파 범위 | {expected_low:,.0f}--{expected_high:,.0f} |",
        "", "## 해석", "",
        "2025년 로그우도 개선이 양수이면 가상 상한으로 선택된 양의 마권수 벡터에서 "
        "무조건부 다항보다 DM이 더 잘 맞는다는 뜻이다. 상한 이하라는 선택사건을 "
        "조건화한 우도가 아니므로 `alpha`를 실제 상한 셀의 구조적 이질성으로 해석할 "
        "수 없다. 실제 상한 외삽은 구조적 0을 검정하거나 식별하지 않으며 회계적 "
        f"부분식별 구간을 대체하지 않는다. 기대값 범위의 상단은 {zero_lower_races:,}개 "
        "경주에서 회계적 `R` 하한이 0인 극단 시나리오를 합산한 값이다.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--summary-out", type=pathlib.Path,
        default=pathlib.Path("데이터/dirichlet_multinomial_fit.csv"),
    )
    parser.add_argument(
        "--actual-out", type=pathlib.Path,
        default=pathlib.Path("데이터/dirichlet_multinomial_actual.csv.gz"),
    )
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/dirichlet_multinomial.md"),
    )
    args = parser.parse_args()
    races = load_races(args.data / "races.jsonl.gz")
    wanted = primary_race_ids(args.data / "trifecta_feasible_sets.csv.gz")
    grids = load_grids(args.data, races, wanted)
    summary = summarize(virtual_vectors(races, grids))
    actual = actual_rows(args.data / "trifecta_feasible_sets.csv.gz", float(summary[-1]["alpha"]))
    write_csv(args.summary_out, summary, SUMMARY_FIELDS, zipped=False)
    write_csv(args.actual_out, actual, ACTUAL_FIELDS, zipped=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report(summary, actual), encoding="utf-8")
    print(f"wrote {args.summary_out}: {len(summary)} rows")
    print(f"wrote {args.actual_out}: {len(actual):,} rows")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
