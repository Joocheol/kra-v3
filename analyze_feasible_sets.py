#!/usr/bin/env python3
"""Compute model-free trifecta ticket and no-bet bounds for every race."""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import pathlib
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from kra.feasible import (
    capped_ticket_upper,
    constrained_capped_bounds,
    displayed_ticket_interval,
)


POOL_LABEL = "삼쌍승식"
PAGE_KEY = "3Both"
NUMERIC_ODDS = re.compile(r"^[0-9]+\.[0-9]$")


@dataclass
class GridTotals:
    uncensored_cells: int = 0
    capped_cells: int = 0
    incompatible_cells: int = 0
    ticket_min: int = 0
    ticket_max: int = 0


FIELDS = [
    "race_id", "sales_won", "total_tickets", "starters",
    "expected_combinations", "observed_numeric_cells", "uncensored_cells",
    "capped_cells", "rounding_incompatible_cells", "uncensored_ticket_min",
    "uncensored_ticket_max", "raw_residual_min", "raw_residual_max",
    "cap_ticket_upper", "strict_feasible", "feasible_residual_min",
    "feasible_residual_max", "min_unbet_cells", "max_unbet_cells",
    "individual_cap_ticket_min", "individual_cap_ticket_max",
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


def scan_grids(data_dir: pathlib.Path, races: dict[str, dict]) -> dict[str, GridTotals]:
    totals = {race_id: GridTotals() for race_id in races}
    partitions = sorted((data_dir / "cells" / f"page_key={PAGE_KEY}").glob("*.csv.gz"))
    if not partitions:
        raise FileNotFoundError(f"no {PAGE_KEY} partitions")
    for index, path in enumerate(partitions, 1):
        print(f"scan {index}/{len(partitions)}: {path.name}", flush=True)
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                raw = row["cell_raw"]
                if row["section"] != "body" or not NUMERIC_ODDS.fullmatch(raw):
                    continue
                race = races.get(row["race_id"])
                if race is None:
                    raise ValueError(f"grid race missing from race table: {row['race_id']}")
                item = totals[row["race_id"]]
                if raw == "9999.9":
                    item.capped_cells += 1
                    continue
                sales = _won(race["sales"][POOL_LABEL])
                candidates = displayed_ticket_interval(sales, Decimal(raw))
                item.uncensored_cells += 1
                if not candidates:
                    item.incompatible_cells += 1
                else:
                    item.ticket_min += candidates.start
                    item.ticket_max += candidates.stop - 1
    return totals


def build_rows(races: dict[str, dict], totals: dict[str, GridTotals]) -> list[dict]:
    rows = []
    for race_id in sorted(races):
        race = races[race_id]
        grid = totals[race_id]
        sales = _won(race["sales"][POOL_LABEL])
        if sales % 100:
            raise ValueError(f"{race_id}: sales not divisible by 100: {sales}")
        total_tickets = sales // 100
        starters = len(race["horses"]) - len(race.get("scratched") or [])
        expected = starters * (starters - 1) * (starters - 2)
        observed = grid.uncensored_cells + grid.capped_cells
        residual_min = total_tickets - grid.ticket_max
        residual_max = total_tickets - grid.ticket_min
        upper = capped_ticket_upper(sales)
        bounds = None
        if grid.incompatible_cells == 0 and observed == expected:
            bounds = constrained_capped_bounds(
                grid.capped_cells, upper, residual_min, residual_max
            )
        rows.append({
            "race_id": race_id,
            "sales_won": sales,
            "total_tickets": total_tickets,
            "starters": starters,
            "expected_combinations": expected,
            "observed_numeric_cells": observed,
            "uncensored_cells": grid.uncensored_cells,
            "capped_cells": grid.capped_cells,
            "rounding_incompatible_cells": grid.incompatible_cells,
            "uncensored_ticket_min": grid.ticket_min,
            "uncensored_ticket_max": grid.ticket_max,
            "raw_residual_min": residual_min,
            "raw_residual_max": residual_max,
            "cap_ticket_upper": upper,
            "strict_feasible": int(bounds is not None),
            "feasible_residual_min": bounds.residual_min if bounds else "",
            "feasible_residual_max": bounds.residual_max if bounds else "",
            "min_unbet_cells": bounds.min_zero_cells if bounds else "",
            "max_unbet_cells": bounds.max_zero_cells if bounds else "",
            "individual_cap_ticket_min": bounds.cell_ticket_min if bounds else "",
            "individual_cap_ticket_max": bounds.cell_ticket_max if bounds else "",
        })
    return rows


def write_csv_gz(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
        tmp = pathlib.Path(raw.name)
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
    tmp.replace(path)


def _pct(n: int, d: int) -> str:
    return f"{100*n/d:.3f}%" if d else "해당 없음"


def report(rows: list[dict]) -> str:
    capped = [r for r in rows if r["capped_cells"]]
    feasible = [r for r in capped if r["strict_feasible"]]
    complete = [r for r in rows if r["observed_numeric_cells"] == r["expected_combinations"]]
    incompatible = [r for r in rows if r["rounding_incompatible_cells"]]
    forced = [r for r in feasible if r["min_unbet_cells"] > 0]
    capped_cells = sum(r["capped_cells"] for r in capped)
    feasible_cells = sum(r["capped_cells"] for r in feasible)
    lower_zeros = sum(r["min_unbet_cells"] for r in feasible)
    upper_zeros = sum(r["max_unbet_cells"] for r in feasible)
    bad_cells = sum(r["rounding_incompatible_cells"] for r in rows)
    lines = [
        "# 삼쌍승식 `9999.9` 셀의 회계적 feasible set과 무투표 하한",
        "",
        "## 결론",
        "",
        f"전체 {len(rows):,}경주 중 `9999.9`가 있는 경주는 {len(capped):,}개이고, "
        f"그중 엄격한 반올림·총합 제약이 동시에 성립하는 경주는 {len(feasible):,}개"
        f"({_pct(len(feasible), len(capped))})다.",
        "",
        f"엄격 feasible 경주의 검열 셀 {feasible_cells:,}개에 대해 회계 제약만으로 "
        f"확정되는 무투표 셀의 합계 하한은 **{lower_zeros:,}개**"
        f"({_pct(lower_zeros, feasible_cells)})다. 경주별 하한이 양수인 경주는 "
        f"{len(forced):,}개다. 가능한 무투표 셀의 합계 상한은 {upper_zeros:,}개다. "
        "이 범위는 확률모형을 전혀 쓰지 않은 부분식별 결과다.",
        "",
        "## 정의와 계산",
        "",
        "경주별 삼쌍승식 총판매 마권 수를 `T=S/100`, 미검열 셀에서 역산한 "
        "마권 수 합의 범위를 `[L,U]`, 검열 셀 수를 `C`라 했다. 각 검열 셀은 "
        "연승 사례가 보여 준 무투표 가능성을 포함해 `n ∈ {0,1,...,N}`으로 두었다.",
        "",
        "```text",
        "R_min = T - U",
        "R_max = T - L",
        "검열 셀 합계 R ∈ [R_min,R_max] ∩ [0,CN]",
        "확정 무투표 수 하한 = max(0, C - R_max*)",
        "가능 무투표 수 상한 = C - ceil(R_min*/N)",
        "```",
        "",
        "별표는 두 구간을 교차한 뒤의 끝점이다. 미검열 배당은 소수 첫째 자리 "
        "half-up 반올림 구간을 정확한 유리수로 역산했다. 이 계산은 다항분포, "
        "Harville, 다른 승식 배당을 사용하지 않는다.",
        "",
        "## 자료 완전성과 엄격 feasible 표본",
        "",
        "| 검사 | 경주/셀 |",
        "| --- | ---: |",
        f"| 전체 경주 | {len(rows):,} |",
        f"| 조합 수가 출전두수의 순열과 정확히 일치한 경주 | {len(complete):,} "
        f"({_pct(len(complete), len(rows))}) |",
        f"| `9999.9` 경주 | {len(capped):,} |",
        f"| 엄격 feasible `9999.9` 경주 | {len(feasible):,} "
        f"({_pct(len(feasible), len(capped))}) |",
        f"| 최종 매출액과 반올림상 양립하지 않는 미검열 셀 | {bad_cells:,}셀, "
        f"{len(incompatible):,}경주 |",
        "",
        "반올림 불일치 셀이 하나라도 있거나 조합 격자가 불완전한 경주는 엄격 "
        "feasible 결과에서 제외했다. 이들을 가장 가까운 정수로 임의 보정하지 않았다. "
        "따라서 위 하한은 전체 자료의 하한이 아니라 **엄격 feasible 부분표본에서 "
        "확정된 하한**이다.",
        "",
        "## 해석",
        "",
        "- `min_unbet_cells > 0`이면 그 경주에서는 어떤 모형을 쓰더라도 적어도 그 "
        "  수만큼의 `9999.9` 셀이 `n=0`이어야 한다.",
        "- 하한이 0이라고 해서 모든 셀이 판매됐다는 뜻은 아니다. 단지 총합만으로는 "
        "  무투표를 강제하지 못한다는 뜻이다.",
        "- `max_unbet_cells`는 반대로 무투표일 수 있는 최대 셀 수다. 두 값 사이의 "
        "  불확실성을 줄이는 단계에서만 희소 다항모형이나 다른 승식 정보를 쓴다.",
        "- KRA 상세결과로 확인한 상한 초과 당첨 142건은 `n>0` 라벨이지만 무작위 "
        "  표본이 아니므로 이 하한 계산에는 넣지 않았다.",
        "",
        "전체 경주별 결과는 `데이터/trifecta_feasible_sets.csv.gz`에 있다.",
        "",
    ]
    if forced:
        top = sorted(forced, key=lambda r: (r["min_unbet_cells"], r["capped_cells"]), reverse=True)[:10]
        lines.extend([
            "## 확정 무투표 하한이 큰 경주",
            "",
            "| race_id | 검열 셀 C | 셀별 N | 잔여 마권 feasible 범위 | 무투표 하한 | 무투표 상한 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for r in top:
            lines.append(
                f"| {r['race_id']} | {r['capped_cells']:,} | {r['cap_ticket_upper']:,} | "
                f"{r['feasible_residual_min']:,}--{r['feasible_residual_max']:,} | "
                f"{r['min_unbet_cells']:,} | {r['max_unbet_cells']:,} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--out", type=pathlib.Path,
        default=pathlib.Path("데이터/trifecta_feasible_sets.csv.gz"),
    )
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/trifecta_feasible_sets.md"),
    )
    args = parser.parse_args()
    races = load_races(args.data / "races.jsonl.gz")
    totals = scan_grids(args.data, races)
    rows = build_rows(races, totals)
    write_csv_gz(args.out, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report(rows), encoding="utf-8")
    print(f"wrote {args.out} ({len(rows):,} races)")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
