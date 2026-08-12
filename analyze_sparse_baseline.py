#!/usr/bin/env python3
"""Sparse symmetric-multinomial baseline for actually capped trifecta cells."""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import math
import pathlib
import tempfile


FIELDS = [
    "race_id", "year", "meet", "capped_cells", "residual_min", "residual_mid",
    "residual_max", "tickets_per_cell_mid", "deterministic_min_zeros",
    "deterministic_max_zeros", "expected_zeros_at_residual_max",
    "expected_zeros_at_residual_mid", "expected_zeros_at_residual_min",
    "variance_zeros_at_residual_mid",
]


def _p_empty(cells: int, tickets: int) -> float:
    if tickets == 0:
        return 1.0
    if cells == 1:
        return 0.0
    return math.exp(tickets * math.log1p(-1.0 / cells))


def occupancy_moments(cells: int, tickets: int) -> tuple[float, float]:
    """Mean and variance of empty boxes after uniform multinomial allocation."""
    if cells <= 0 or tickets < 0:
        raise ValueError("invalid occupancy inputs")
    if tickets == 0:
        return float(cells), 0.0
    p0 = _p_empty(cells, tickets)
    mean = cells * p0
    if cells == 1:
        return mean, 0.0
    p00 = math.exp(tickets * math.log1p(-2.0 / cells)) if cells > 2 else 0.0
    variance = (
        cells * p0 * (1 - p0)
        + cells * (cells - 1) * (p00 - p0 * p0)
    )
    return mean, max(0.0, variance)


def load_rows(path: pathlib.Path) -> list[dict[str, object]]:
    out = []
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
            mean_lo_tickets, _ = occupancy_moments(cells, lo)
            mean_mid, variance_mid = occupancy_moments(cells, mid)
            mean_hi_tickets, _ = occupancy_moments(cells, hi)
            out.append({
                "race_id": row["race_id"],
                "year": row["year"],
                "meet": row["meet"],
                "capped_cells": cells,
                "residual_min": lo,
                "residual_mid": mid,
                "residual_max": hi,
                "tickets_per_cell_mid": format(mid / cells, ".12g"),
                "deterministic_min_zeros": int(row["min_unbet_cells"]),
                "deterministic_max_zeros": int(row["max_unbet_cells"]),
                # More allocated tickets imply fewer empty cells.
                "expected_zeros_at_residual_max": format(mean_hi_tickets, ".12g"),
                "expected_zeros_at_residual_mid": format(mean_mid, ".12g"),
                "expected_zeros_at_residual_min": format(mean_lo_tickets, ".12g"),
                "variance_zeros_at_residual_mid": format(variance_mid, ".12g"),
            })
    return out


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


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * probability)]


def make_report(rows: list[dict[str, object]]) -> str:
    cells = sum(int(row["capped_cells"]) for row in rows)
    deterministic_lo = sum(int(row["deterministic_min_zeros"]) for row in rows)
    deterministic_hi = sum(int(row["deterministic_max_zeros"]) for row in rows)
    expected_low = sum(float(row["expected_zeros_at_residual_max"]) for row in rows)
    expected_mid = sum(float(row["expected_zeros_at_residual_mid"]) for row in rows)
    expected_high = sum(float(row["expected_zeros_at_residual_min"]) for row in rows)
    variance = sum(float(row["variance_zeros_at_residual_mid"]) for row in rows)
    sd = math.sqrt(variance)
    normal_low = max(0.0, expected_mid - 1.96 * sd)
    normal_high = min(float(cells), expected_mid + 1.96 * sd)
    lambdas = [float(row["tickets_per_cell_mid"]) for row in rows]
    expected_shares = [
        float(row["expected_zeros_at_residual_mid"]) / int(row["capped_cells"])
        for row in rows
    ]
    zero_lower_races = sum(int(row["residual_min"]) == 0 for row in rows)
    lines = [
        "# 실제 `9999.9` 셀의 대칭 희소 다항 기준모형", "",
        "## 모형과 역할", "",
        "2022--2025년 엄격 회계검사를 통과한 실제 검열 경주만 사용한다. 경주별 "
        "검열 셀 수를 `C`, 그 셀에 배분될 잔여 100원 마권 수를 `R`이라 하고, "
        "조건부로 `R`장을 `C`개 셀에 동일확률로 다항 배분한다. 이는 가상 상한 "
        "검증이 선택한 최적모형이 아니라 추가 구조를 가장 적게 두는 대칭 기준선이다. "
        "가상 상한 표본과 실제 상한 대상의 지원집합이 달라 실제 관측자료의 조건부 "
        "우도모형으로 해석하지 않는다.", "",
        "```text",
        "E[무투표 셀 | C,R] = C(1-1/C)^R",
        "```", "",
        "이 값은 회계로 증명된 식별구간이 아니라 명시적인 확률모형의 결과다. `R`의 "
        "반올림 식별구간은 그대로 전파하며, 구조적 0을 추가하는 모형은 아직 넣지 않는다.", "",
        "## 전체 결과", "",
        "| 항목 | 값 |",
        "| --- | ---: |",
        f"| 경주 | {len(rows):,} |",
        f"| 실제 `9999.9` 셀 | {cells:,} |",
        f"| 회계만의 무투표 구간 | {deterministic_lo:,}--{deterministic_hi:,} |",
        f"| 대칭 다항 기대값 (`R` 중간값) | {expected_mid:.3e} "
        f"({100*expected_mid/cells:.3e}%) |",
        f"| `R` 식별구간을 전파한 기대값 범위 | {expected_low:,.0f}--{expected_high:,.0f} |",
        f"| 경주 내 다항변동만의 합산 표준편차 | {sd:.3e} |",
        f"| 참고 정규근사 95% 범위 (`R` 중간값 고정) | "
        f"{normal_low:.3e}--{normal_high:.3e} |",
        "", "## 경주별 희소성", "",
        "| 통계 | 25% | 중앙값 | 75% |",
        "| --- | ---: | ---: | ---: |",
        f"| 검열 셀당 잔여마권 `R/C` | {_quantile(lambdas,.25):.2f} | "
        f"{_quantile(lambdas,.50):.2f} | {_quantile(lambdas,.75):.2f} |",
        f"| 기대 무투표 비율 | {_quantile(expected_shares,.25):.2%} | "
        f"{_quantile(expected_shares,.50):.2%} | {_quantile(expected_shares,.75):.2%} |",
        "", "## 해석 경계", "",
        "가상 상한 검증은 양의 작은 마권수의 조합 간 배분을 검증할 뿐 실제 0의 "
        "추가 발생 여부를 검정하지 못한다. 따라서 위 결과는 zero-inflated 결론이 "
        "아니라, 이후 Dirichlet--multinomial·logistic-normal·구조적 0 확장이 이겨야 "
        f"하는 사전등록된 기준선이다. `R` 하한에서 기대값 상단이 커지는 것은 {zero_lower_races:,}개 "
        "경주의 회계적 잔여총량 하한이 0이기 때문이다. 경주별 결과는 "
        "`데이터/sparse_multinomial_baseline.csv.gz`에 있다.", "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=pathlib.Path,
        default=pathlib.Path("데이터/trifecta_feasible_sets.csv.gz"),
    )
    parser.add_argument(
        "--out", type=pathlib.Path,
        default=pathlib.Path("데이터/sparse_multinomial_baseline.csv.gz"),
    )
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/sparse_multinomial_baseline.md"),
    )
    args = parser.parse_args()
    rows = load_rows(args.input)
    write_csv_gz(args.out, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(make_report(rows), encoding="utf-8")
    print(f"wrote {args.out}: {len(rows):,} rows")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
