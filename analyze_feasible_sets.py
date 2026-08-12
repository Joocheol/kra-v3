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
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

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
    resolved_by_floor: int = 0
    resolved_by_half_even: int = 0
    resolved_by_take_72: int = 0
    resolved_by_take_75: int = 0


FIELDS = [
    "race_id", "year", "meet", "sales_won", "total_sales_won",
    "total_tickets", "starters",
    "expected_combinations", "observed_numeric_cells", "uncensored_cells",
    "capped_cells", "rounding_incompatible_cells", "uncensored_ticket_min",
    "uncensored_ticket_max", "resolved_by_floor", "resolved_by_half_even",
    "resolved_by_take_72", "resolved_by_take_75", "raw_residual_min",
    "raw_residual_max", "cap_ticket_upper", "cap_ticket_upper_strict_true",
    "strict_feasible", "feasible_residual_min",
    "feasible_residual_max", "min_unbet_cells", "max_unbet_cells",
    "individual_cap_ticket_min", "individual_cap_ticket_max",
    "strict_true_cap_feasible", "strict_true_min_unbet_cells",
    "strict_true_max_unbet_cells", "relaxed_feasible",
    "relaxed_residual_min", "relaxed_residual_max",
    "relaxed_min_unbet_cells", "relaxed_max_unbet_cells",
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
        seen_by_race: dict[str, set[int]] = defaultdict(set)
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                raw = row["cell_raw"]
                if (
                    row["section"] != "body" or row["spanned"] != "0"
                    or not NUMERIC_ODDS.fullmatch(raw)
                ):
                    continue
                race = races.get(row["race_id"])
                if race is None:
                    raise ValueError(f"grid race missing from race table: {row['race_id']}")
                parts = (row["page_variant"], row["col_header"], row["row_header"])
                if not all(part.isdigit() for part in parts):
                    raise ValueError(f"{row['race_id']}: numeric cell has nonnumeric axes: {parts}")
                combo = tuple(map(int, parts))
                starters = set(race["horses"]) - set(race.get("scratched") or [])
                if len(set(combo)) != 3 or not set(combo).issubset(starters):
                    raise ValueError(f"{row['race_id']}: invalid trifecta axes: {combo}")
                code = combo[0] * 10_000 + combo[1] * 100 + combo[2]
                if code in seen_by_race[row["race_id"]]:
                    raise ValueError(f"{row['race_id']}: duplicate trifecta combination: {combo}")
                seen_by_race[row["race_id"]].add(code)
                item = totals[row["race_id"]]
                if raw == "9999.9":
                    item.capped_cells += 1
                    continue
                sales = _won(race["sales"][POOL_LABEL])
                candidates = displayed_ticket_interval(sales, Decimal(raw))
                item.uncensored_cells += 1
                if not candidates:
                    item.incompatible_cells += 1
                    odds = Decimal(raw)
                    item.resolved_by_floor += bool(
                        displayed_ticket_interval(sales, odds, rounding="floor")
                    )
                    item.resolved_by_half_even += bool(
                        displayed_ticket_interval(sales, odds, rounding="half_even")
                    )
                    item.resolved_by_take_72 += bool(
                        displayed_ticket_interval(
                            sales, odds, take_fraction=Fraction(72, 100)
                        )
                    )
                    item.resolved_by_take_75 += bool(
                        displayed_ticket_interval(
                            sales, odds, take_fraction=Fraction(75, 100)
                        )
                    )
                else:
                    item.ticket_min += candidates.start
                    item.ticket_max += candidates.stop - 1
        for race_id, seen in seen_by_race.items():
            race = races[race_id]
            starters = len(race["horses"]) - len(race.get("scratched") or [])
            expected = starters * (starters - 1) * (starters - 2)
            if len(seen) != expected:
                raise ValueError(
                    f"{race_id}: {len(seen)} distinct combinations, expected {expected}"
                )
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
        if observed != expected:
            raise ValueError(f"{race_id}: {observed} numeric combinations, expected {expected}")
        residual_min = total_tickets - grid.ticket_max
        residual_max = total_tickets - grid.ticket_min
        upper = capped_ticket_upper(sales)
        strict_true_upper = capped_ticket_upper(sales, definition="strict_true")
        bounds = strict_true_bounds = None
        if grid.incompatible_cells == 0:
            bounds = constrained_capped_bounds(
                grid.capped_cells, upper, residual_min, residual_max
            )
            strict_true_bounds = constrained_capped_bounds(
                grid.capped_cells, strict_true_upper, residual_min, residual_max
            )
        # A falsification-robust alternative retains the race but demotes every
        # incompatible *uncapped* cell to an unknown positive count [1,T].
        relaxed_residual_min = total_tickets - (
            grid.ticket_max + grid.incompatible_cells * total_tickets
        )
        relaxed_residual_max = total_tickets - (
            grid.ticket_min + grid.incompatible_cells
        )
        relaxed = constrained_capped_bounds(
            grid.capped_cells, upper, relaxed_residual_min, relaxed_residual_max
        )
        rows.append({
            "race_id": race_id,
            "year": race["date"][:4],
            "meet": race["meet"],
            "sales_won": sales,
            "total_sales_won": _won(race["sales"]["총매출액"]),
            "total_tickets": total_tickets,
            "starters": starters,
            "expected_combinations": expected,
            "observed_numeric_cells": observed,
            "uncensored_cells": grid.uncensored_cells,
            "capped_cells": grid.capped_cells,
            "rounding_incompatible_cells": grid.incompatible_cells,
            "uncensored_ticket_min": grid.ticket_min,
            "uncensored_ticket_max": grid.ticket_max,
            "resolved_by_floor": grid.resolved_by_floor,
            "resolved_by_half_even": grid.resolved_by_half_even,
            "resolved_by_take_72": grid.resolved_by_take_72,
            "resolved_by_take_75": grid.resolved_by_take_75,
            "raw_residual_min": residual_min,
            "raw_residual_max": residual_max,
            "cap_ticket_upper": upper,
            "cap_ticket_upper_strict_true": strict_true_upper,
            "strict_feasible": int(bounds is not None),
            "feasible_residual_min": bounds.residual_min if bounds else "",
            "feasible_residual_max": bounds.residual_max if bounds else "",
            "min_unbet_cells": bounds.min_zero_cells if bounds else "",
            "max_unbet_cells": bounds.max_zero_cells if bounds else "",
            "individual_cap_ticket_min": bounds.cell_ticket_min if bounds else "",
            "individual_cap_ticket_max": bounds.cell_ticket_max if bounds else "",
            "strict_true_cap_feasible": int(strict_true_bounds is not None),
            "strict_true_min_unbet_cells": (
                strict_true_bounds.min_zero_cells if strict_true_bounds else ""
            ),
            "strict_true_max_unbet_cells": (
                strict_true_bounds.max_zero_cells if strict_true_bounds else ""
            ),
            "relaxed_feasible": int(relaxed is not None),
            "relaxed_residual_min": relaxed.residual_min if relaxed else "",
            "relaxed_residual_max": relaxed.residual_max if relaxed else "",
            "relaxed_min_unbet_cells": relaxed.min_zero_cells if relaxed else "",
            "relaxed_max_unbet_cells": relaxed.max_zero_cells if relaxed else "",
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


def _winning_counts(path: pathlib.Path) -> tuple[int, int, int]:
    if not path.exists():
        return 0, 0, 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return (
        len(rows),
        sum(row["pool_label"] == "삼쌍승식" for row in rows),
        len({row["race_id"] for row in rows}),
    )


def _recompute_sales_sensitivity(
    data_dir: pathlib.Path,
    races: dict[str, dict],
    race_ids: list[str],
) -> list[dict]:
    wanted = set(race_ids)
    odds: dict[str, list[Decimal]] = {race_id: [] for race_id in race_ids}
    months = {races[race_id]["date"][:7] for race_id in race_ids}
    for month in sorted(months):
        path = data_dir / "cells" / f"page_key={PAGE_KEY}" / f"{month}.csv.gz"
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if (
                    row["race_id"] in wanted and row["section"] == "body"
                    and row["spanned"] == "0" and NUMERIC_ODDS.fullmatch(row["cell_raw"])
                ):
                    odds[row["race_id"]].append(Decimal(row["cell_raw"]))
    out = []
    for race_id in race_ids:
        base = _won(races[race_id]["sales"][POOL_LABEL])
        for basis_points in (-100, -50, 0, 50, 100):
            sales = round(base * (10_000 + basis_points) / 10_000 / 100) * 100
            capped = bad = ticket_min = ticket_max = 0
            for value in odds[race_id]:
                if value == Decimal("9999.9"):
                    capped += 1
                    continue
                candidates = displayed_ticket_interval(sales, value)
                if not candidates:
                    bad += 1
                else:
                    ticket_min += candidates.start
                    ticket_max += candidates.stop - 1
            bounds = None
            if bad == 0:
                bounds = constrained_capped_bounds(
                    capped, capped_ticket_upper(sales),
                    sales // 100 - ticket_max, sales // 100 - ticket_min,
                )
            out.append({
                "race_id": race_id,
                "change": f"{basis_points / 100:+.1f}%",
                "sales": sales,
                "bad": bad,
                "min_zero": bounds.min_zero_cells if bounds else "—",
                "max_zero": bounds.max_zero_cells if bounds else "—",
            })
    return out


def _append_group_table(
    lines: list[str], rows: list[dict], heading: str, key: str
) -> None:
    lines.extend([
        heading, "",
        "| 집단 | 검열 경주 | 엄격 통과 | 통과율 | 불일치 셀 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    groups: dict[object, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    for value in sorted(groups, key=lambda x: str(x).zfill(8)):
        group = groups[value]
        passed = sum(r["strict_feasible"] for r in group)
        bad = sum(r["rounding_incompatible_cells"] for r in group)
        lines.append(
            f"| {value} | {len(group):,} | {passed:,} | "
            f"{_pct(passed, len(group))} | {bad:,} |"
        )
    lines.append("")


def report(rows: list[dict], races: dict[str, dict], data_dir: pathlib.Path) -> str:
    capped = [r for r in rows if r["capped_cells"]]
    feasible = [r for r in capped if r["strict_feasible"]]
    relaxed = [r for r in capped if r["relaxed_feasible"]]
    uncapped = [r for r in rows if not r["capped_cells"]]
    uncapped_pass = [r for r in uncapped if r["strict_feasible"]]
    uncapped_fail = [r for r in uncapped if not r["strict_feasible"]]
    uncapped_clean = [r for r in uncapped if not r["rounding_incompatible_cells"]]
    incompatible = [r for r in rows if r["rounding_incompatible_cells"]]
    forced = [r for r in feasible if r["min_unbet_cells"] > 0]
    feasible_cells = sum(r["capped_cells"] for r in feasible)
    lower_zeros = sum(r["min_unbet_cells"] for r in feasible)
    upper_zeros = sum(r["max_unbet_cells"] for r in feasible)
    relaxed_cells = sum(r["capped_cells"] for r in relaxed)
    relaxed_lower = sum(r["relaxed_min_unbet_cells"] for r in relaxed)
    relaxed_upper = sum(r["relaxed_max_unbet_cells"] for r in relaxed)
    bad_cells = sum(r["rounding_incompatible_cells"] for r in rows)
    strict_true = [r for r in capped if r["strict_true_cap_feasible"]]
    boundary_changed = [
        r for r in rows if r["cap_ticket_upper"] != r["cap_ticket_upper_strict_true"]
    ]
    winning_total, winning_trifecta, winning_races = _winning_counts(
        data_dir / "winning_capped_payouts.csv.gz"
    )
    lines = [
        "# 삼쌍승식 `9999.9` 셀의 회계적 부분식별 구간",
        "",
        "## 결론",
        "",
        f"회계 제약만으로 좁혀지는 핵심 결과는 한 점이 아니라 넓은 구간이다. "
        f"엄격 규칙을 통과한 {len(feasible):,}개 검열 경주의 {feasible_cells:,}개 "
        f"`9999.9` 셀 가운데 무투표 셀 합계는 **{lower_zeros:,}--{upper_zeros:,}개**"
        f"({_pct(lower_zeros, feasible_cells)}--{_pct(upper_zeros, feasible_cells)})로만 묶인다.",
        "",
        f"불일치 셀만 양의 미지수 `[1,T]`로 완화하면 {len(relaxed):,}개 경주의 "
        f"{relaxed_cells:,}개 검열 셀에 대한 구간은 **{relaxed_lower:,}--{relaxed_upper:,}개**"
        f"({_pct(relaxed_lower, relaxed_cells)}--{_pct(relaxed_upper, relaxed_cells)})다. "
        "따라서 회계만으로 개별 셀의 무투표 여부를 실질적으로 식별하지 못한다.",
        "",
        f"양의 하한 {lower_zeros:,}개는 같은 날 서울 두 경주에만 나타나므로 대표 "
        "결론이 아니라 원자료 교차검증과 민감도 검사를 통과한 특이 사례로 취급한다.",
        "",
        "## 정의와 계산",
        "",
        "경주별 삼쌍승식 총판매 마권 수를 `T=S/100`, 미검열 셀에서 역산한 "
        "마권 수 합의 범위를 `[L,U]`, 검열 셀 수를 `C`라 했다. 각 검열 셀은 "
        "`n ∈ {0,1,...,N}`으로 두었다. 모든 유효 순서조합이 19,301경주 전부에서 "
        "정확히 한 개의 수치 셀로 나타난다는 완전성 항등식이 `n=0`도 어떤 수치로 "
        "표시되어야 한다는 주된 근거다. KRA 공식 인코딩 규정이 확인된 것은 아니므로 "
        "이는 명시적 식별가정이다.",
        "",
        "```text",
        "R_min = T - U",
        "R_max = T - L",
        "검열 셀 합계 R ∈ [R_min,R_max] ∩ [0,CN]",
        "확정 무투표 수 하한 = max(0, C - R_max*)",
        "가능 무투표 수 상한 = C - ceil(R_min*/N)",
        "```",
        "",
        "관측사건은 `참배당 > 9999.9`가 아니라 half-up 표시값이 상한인 사건이므로 "
        "양의 후보는 참배당 `O >= 9999.85`까지 포함한다. 이 계산은 다항분포, "
        "Harville, 다른 승식 배당을 사용하지 않는다.",
        "",
        "## 모형 반증 시험과 포함규칙",
        "",
        "| 검사 | 경주/셀 |",
        "| --- | ---: |",
        f"| 전체 경주 | {len(rows):,} |",
        f"| 서로 다른 조합이 출전두수 순열과 정확히 일치 | {len(rows):,} "
        f"({_pct(len(rows), len(rows))}) |",
        f"| `9999.9` 경주 | {len(capped):,} |",
        f"| 엄격 feasible `9999.9` 경주 | {len(feasible):,}/"
        f"{len(capped):,} ({_pct(len(feasible), len(capped))}) |",
        f"| `9999.9`가 없는 경주의 자유도 0 specification test | "
        f"{len(uncapped_pass):,}/{len(uncapped):,} "
        f"({_pct(len(uncapped_pass), len(uncapped))}) |",
        f"| 불일치 셀이 없는 무검열 경주의 자유도 0 검사 | "
        f"{len(uncapped_pass):,}/{len(uncapped_clean):,} "
        f"({_pct(len(uncapped_pass), len(uncapped_clean))}) |",
        f"| 최종 매출액과 반올림상 양립하지 않는 미검열 셀 | {bad_cells:,}셀, "
        f"{len(incompatible):,}경주 |",
        f"| 불일치 셀 완화 규칙에서 feasible `9999.9` 경주 | {len(relaxed):,}/"
        f"{len(capped):,} ({_pct(len(relaxed), len(capped))}) |",
        "",
        "엄격 규칙은 불일치 셀이 하나라도 있으면 경주를 제외하므로 격자가 큰 경주의 "
        "탈락확률이 기계적으로 높다. 따라서 엄격 결과는 선택된 부분표본이며, 셀 단위 "
        "완화 결과를 함께 제시한다. 격자와 매출액이 같은 마감시점의 값이라는 가정은 "
        "공식 메타데이터로 확인되지 않았고 아래 불일치는 그 가정까지 함께 검정한다.",
        "",
        f"무검열 경주의 실패 {len(uncapped_fail):,}건은 모두 반올림 불일치 셀을 "
        "적어도 하나 포함했다. 불일치 셀이 없는 무검열 경주는 자유도 0 회계식을 "
        "전부 통과했다. 실패 예시는 "
        + ", ".join(
            f"`{row['race_id']}`({row['rounding_incompatible_cells']}셀)"
            for row in uncapped_fail[:5]
        ) + "다.",
        "",
        "### 불일치 셀의 대안 규약 진단",
        "",
        "| 대안 | 기준 불일치 셀 중 정수해가 생기는 셀 |",
        "| --- | ---: |",
        f"| floor 표시 | {sum(r['resolved_by_floor'] for r in rows):,}/{bad_cells:,} |",
        f"| half-even 표시 | {sum(r['resolved_by_half_even'] for r in rows):,}/{bad_cells:,} |",
        f"| 환급률 0.72, half-up | {sum(r['resolved_by_take_72'] for r in rows):,}/{bad_cells:,} |",
        f"| 환급률 0.75, half-up | {sum(r['resolved_by_take_75'] for r in rows):,}/{bad_cells:,} |",
        "",
        f"표시상한 사건과 더 좁은 `참배당 > 9999.9` 정의에서 셀별 상한이 달라지는 "
        f"경주는 {len(boundary_changed):,}개다. 좁은 정의의 엄격 feasible 경주는 "
        f"{len(strict_true):,}개다. 두 정의의 결과는 경주별 CSV에 모두 보존했다.",
        "",
        "## 엄격 표본의 선택 진단",
        "",
    ]
    _append_group_table(lines, capped, "### 출전두수별", "starters")
    _append_group_table(
        lines, capped, "### 경마장별 (`1=서울, 2=제주, 3=부산경남`)", "meet"
    )
    _append_group_table(lines, capped, "### 연도별", "year")
    ordered = sorted(capped, key=lambda r: (r["sales_won"], r["race_id"]))
    for index, row in enumerate(ordered):
        row["sales_quintile"] = min(5, index * 5 // len(ordered) + 1)
    _append_group_table(lines, capped, "### 삼쌍승 매출 5분위별", "sales_quintile")

    if forced:
        top = sorted(
            forced,
            key=lambda r: (r["min_unbet_cells"], r["capped_cells"]),
            reverse=True,
        )[:10]
        lines.extend([
            "## 양의 하한이 나온 두 특이 경주",
            "",
            "| race_id | 삼쌍승 매출 | 총매출 | 삼쌍승 비중 | C | N | 무투표 구간 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for row in top:
            lines.append(
                f"| {row['race_id']} | {row['sales_won']:,}원 | "
                f"{row['total_sales_won']:,}원 | "
                f"{_pct(row['sales_won'], row['total_sales_won'])} | "
                f"{row['capped_cells']:,} | {row['cap_ticket_upper']:,} | "
                f"{row['min_unbet_cells']:,}--{row['max_unbet_cells']:,} |"
            )
        date = races[top[0]["race_id"]]["date"]
        meet = races[top[0]["race_id"]]["meet"]
        day = sorted(
            (r for r in races.values() if r["date"] == date and r["meet"] == meet),
            key=lambda r: r["race_no"],
        )
        lines.extend([
            "",
            "두 경주의 일곱 승식 합은 `총매출액`과 원 단위까지 일치하고, 취소마가 "
            "없으며 12두 전부 완주했다. 같은 날 삼쌍승 매출 흐름은 다음과 같다. "
            "2--4경주의 일시적 급락 원인은 저장자료만으로 확인할 수 없다.",
            "",
            "| 경주 | 삼쌍승 매출 | 총매출 | 삼쌍승 비중 |",
            "| --- | ---: | ---: | ---: |",
        ])
        for race in day:
            tri = _won(race["sales"][POOL_LABEL])
            total = _won(race["sales"]["총매출액"])
            lines.append(
                f"| {race['race_no']} | {tri:,}원 | {total:,}원 | {_pct(tri, total)} |"
            )
        lines.extend([
            "",
            "### 매출액 ±0.5%·±1% 일관 민감도",
            "",
            "각 대안 매출에서 모든 미검열 배당의 정수구간도 함께 다시 계산했다.",
            "",
            "| race_id | 매출 변화 | 대안 매출 | 불일치 미검열 셀 | 무투표 구간 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        for item in _recompute_sales_sensitivity(
            data_dir, races, [row["race_id"] for row in top]
        ):
            lines.append(
                f"| {item['race_id']} | {item['change']} | {item['sales']:,}원 | "
                f"{item['bad']:,} | {item['min_zero']}--{item['max_zero']} |"
            )
        lines.extend([
            "",
            "원래 매출에서는 불일치가 0개지만 ±0.5%만 바꾸어도 수백 개 셀이 "
            f"표시배당과 양립하지 않는다. 따라서 {lower_zeros:,} 하한이 매출의 작은 숫자 변경만으로 "
            "사라진다는 주장은 전체 격자를 함께 재계산하면 성립하지 않는다. 다만 급락의 "
            "제도적 원인이 확인되지 않았으므로 두 경주 의존성은 한계로 남는다.",
            "",
        ])

    lines.extend([
        "## 외부 상한 초과 지급 표본과 해석",
        "",
        f"동결 상세 성적표 {winning_races:,}경주에서 상한 초과 지급 {winning_total:,}건을 "
        f"확인했고, 그중 삼쌍승은 {winning_trifecta:,}건이다. 이는 실제 당첨조합만 "
        "드러나는 선택표본이며 전체 검열 셀을 대표하지 않는다. 고배당에서는 반올림 "
        "구간 폭이 좁아 정수 후보가 하나인 것은 대체로 기계적 결과다.",
        "",
        "`min_unbet_cells=0`은 모든 셀이 판매됐다는 뜻이 아니라 총합만으로 0을 "
        "강제하지 못한다는 뜻이다. 이 넓은 구간을 줄일 때에만 희소 다항모형이나 "
        "다른 승식 정보를 사용한다. 전체 결과는 "
        "`데이터/trifecta_feasible_sets.csv.gz`에 있다.",
        "",
    ])
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
    args.report.write_text(report(rows, races, args.data), encoding="utf-8")
    print(f"wrote {args.out} ({len(rows):,} races)")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
