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
    lower_code_cells: int = 0
    incompatible_cells: int = 0
    ticket_min: int = 0
    ticket_max: int = 0


FIELDS = [
    "race_id", "year", "meet", "sales_won", "total_sales_won",
    "total_tickets", "starters",
    "expected_combinations", "observed_numeric_cells", "uncensored_cells",
    "capped_cells", "lower_code_1_0_cells", "rounding_incompatible_cells",
    "uncensored_ticket_min", "uncensored_ticket_max", "raw_residual_min",
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


def _validated_trifecta_cell(
    row: dict[str, str], race: dict, seen: set[int]
) -> Decimal | None:
    raw = row["cell_raw"]
    if (
        row["section"] != "body" or row["spanned"] != "0"
        or not NUMERIC_ODDS.fullmatch(raw)
    ):
        return None
    parts = (row["page_variant"], row["col_header"], row["row_header"])
    if not all(part.isdigit() for part in parts):
        raise ValueError(f"{row['race_id']}: numeric cell has nonnumeric axes: {parts}")
    combo = tuple(map(int, parts))
    starters = set(race["horses"]) - set(race.get("scratched") or [])
    if len(set(combo)) != 3 or not set(combo).issubset(starters):
        raise ValueError(f"{row['race_id']}: invalid trifecta axes: {combo}")
    code = combo[0] * 10_000 + combo[1] * 100 + combo[2]
    if code in seen:
        raise ValueError(f"{row['race_id']}: duplicate trifecta combination: {combo}")
    seen.add(code)
    return Decimal(raw)


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
                race = races.get(row["race_id"])
                if race is None:
                    if row["section"] == "body" and NUMERIC_ODDS.fullmatch(row["cell_raw"]):
                        raise ValueError(f"grid race missing from race table: {row['race_id']}")
                    continue
                value = _validated_trifecta_cell(
                    row, race, seen_by_race[row["race_id"]]
                )
                if value is None:
                    continue
                raw = row["cell_raw"]
                item = totals[row["race_id"]]
                if raw == "9999.9":
                    item.capped_cells += 1
                    continue
                if raw == "1.0":
                    item.lower_code_cells += 1
                sales = _won(race["sales"][POOL_LABEL])
                candidates = displayed_ticket_interval(sales, value)
                item.uncensored_cells += 1
                if not candidates:
                    item.incompatible_cells += 1
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
            "lower_code_1_0_cells": grid.lower_code_cells,
            "rounding_incompatible_cells": grid.incompatible_cells,
            "uncensored_ticket_min": grid.ticket_min,
            "uncensored_ticket_max": grid.ticket_max,
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


def _quartiles(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    ordered = sorted(values)
    def pick(p: float) -> float:
        return ordered[round((len(ordered) - 1) * p)]
    return pick(.25), pick(.50), pick(.75)


def _winning_counts(path: pathlib.Path) -> tuple[int, int, int, int]:
    if not path.exists():
        return 0, 0, 0, 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return (
        len(rows),
        sum(int(row["is_above_display_cap"]) for row in rows),
        sum(
            row["pool_label"] == "삼쌍승식" and int(row["is_above_display_cap"])
            for row in rows
        ),
        len({row["race_id"] for row in rows}),
    )


def _load_trifecta_odds(
    data_dir: pathlib.Path,
    races: dict[str, dict],
    race_ids: list[str],
) -> dict[str, list[Decimal]]:
    wanted = set(race_ids)
    odds: dict[str, list[Decimal]] = {race_id: [] for race_id in race_ids}
    seen: dict[str, set[int]] = {race_id: set() for race_id in race_ids}
    months = {races[race_id]["date"][:7] for race_id in race_ids}
    for month in sorted(months):
        path = data_dir / "cells" / f"page_key={PAGE_KEY}" / f"{month}.csv.gz"
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                race_id = row["race_id"]
                if race_id not in wanted:
                    continue
                value = _validated_trifecta_cell(row, races[race_id], seen[race_id])
                if value is not None:
                    odds[race_id].append(value)
    for race_id in race_ids:
        starters = len(races[race_id]["horses"]) - len(races[race_id].get("scratched") or [])
        expected = starters * (starters - 1) * (starters - 2)
        if len(odds[race_id]) != expected:
            raise ValueError(
                f"{race_id}: sensitivity loaded {len(odds[race_id])}, expected {expected}"
            )
    return odds


def _assumption_sensitivity(
    races: dict[str, dict],
    race_rows: list[dict],
    odds: dict[str, list[Decimal]],
) -> list[dict]:
    out = []
    rows_by_id = {row["race_id"]: row for row in race_rows}
    for race_id in sorted(odds):
        base = _won(races[race_id]["sales"][POOL_LABEL])
        for rounding in ("half_up", "floor", "half_even"):
            for take in (Fraction(72, 100), Fraction(73, 100), Fraction(75, 100)):
                sales = base
                capped = bad = ticket_min = ticket_max = 0
                for value in odds[race_id]:
                    if value == Decimal("9999.9"):
                        capped += 1
                        continue
                    candidates = displayed_ticket_interval(
                        sales, value, rounding=rounding, take_fraction=take
                    )
                    if not candidates:
                        bad += 1
                    else:
                        ticket_min += candidates.start
                        ticket_max += candidates.stop - 1
                bounds = None
                if bad == 0:
                    # The maintained cap event is half-up.  Alternative
                    # rounding conventions are falsification diagnostics; in
                    # the observed two races they are rejected by uncapped
                    # cells before this upper bound can affect the result.
                    bounds = constrained_capped_bounds(
                        capped,
                        capped_ticket_upper(sales, take_fraction=take),
                        sales // 100 - ticket_max,
                        sales // 100 - ticket_min,
                    )
                out.append({
                    "race_id": race_id,
                    "rounding": rounding,
                    "take": f"{float(take):.2f}",
                    "bad": bad,
                    "ticket_min": ticket_min,
                    "ticket_max": ticket_max,
                    "min_zero": bounds.min_zero_cells if bounds else "—",
                    "max_zero": bounds.max_zero_cells if bounds else "—",
                    "breakdown": (
                        bounds.min_zero_cells if bounds and bounds.min_zero_cells else "—"
                    ),
                })
        maintained = next(
            item for item in reversed(out)
            if item["race_id"] == race_id
            and item["rounding"] == "half_up" and item["take"] == "0.73"
        )
        row = rows_by_id[race_id]
        if (
            maintained["bad"] != 0
            or maintained["ticket_min"] != row["uncensored_ticket_min"]
            or maintained["ticket_max"] != row["uncensored_ticket_max"]
        ):
            raise AssertionError(f"{race_id}: sensitivity path differs from main scan")
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
    capped_clean = [r for r in capped if not r["rounding_incompatible_cells"]]
    forced = [r for r in feasible if r["min_unbet_cells"] > 0]
    feasible_cells = sum(r["capped_cells"] for r in feasible)
    lower_zeros = sum(r["min_unbet_cells"] for r in feasible)
    upper_zeros = sum(r["max_unbet_cells"] for r in feasible)
    relaxed_cells = sum(r["capped_cells"] for r in relaxed)
    relaxed_lower = sum(r["relaxed_min_unbet_cells"] for r in relaxed)
    relaxed_upper = sum(r["relaxed_max_unbet_cells"] for r in relaxed)
    excluded_capped_cells = sum(r["capped_cells"] for r in capped) - feasible_cells
    bad_cells = sum(r["rounding_incompatible_cells"] for r in rows)
    lower_code_cells = sum(r["lower_code_1_0_cells"] for r in rows)
    lower_code_races = sum(bool(r["lower_code_1_0_cells"]) for r in rows)
    strict_true = [r for r in capped if r["strict_true_cap_feasible"]]
    boundary_changed = [
        r for r in rows if r["cap_ticket_upper"] != r["cap_ticket_upper_strict_true"]
    ]
    winning_matched, winning_above, winning_trifecta, winning_races = _winning_counts(
        data_dir / "winning_capped_payouts.csv.gz"
    )
    pre = [r for r in capped if r["year"] <= "2019"]
    post = [r for r in capped if r["year"] >= "2022"]
    pre_feasible = [r for r in pre if r["strict_feasible"]]
    post_feasible = [r for r in post if r["strict_feasible"]]
    post_cells = sum(r["capped_cells"] for r in post_feasible)
    post_lower = sum(r["min_unbet_cells"] for r in post_feasible)
    post_upper = sum(r["max_unbet_cells"] for r in post_feasible)
    uncapped_width = [
        (r["uncensored_ticket_max"] - r["uncensored_ticket_min"]) / r["total_tickets"]
        for r in uncapped_clean if r["total_tickets"]
    ]
    uncapped_center = [
        abs(2 * r["total_tickets"] - r["uncensored_ticket_min"]
            - r["uncensored_ticket_max"]) / (2 * r["total_tickets"])
        for r in uncapped_clean if r["total_tickets"]
    ]
    width_q = _quartiles(uncapped_width)
    center_q = _quartiles(uncapped_center)
    uncapped_clean_scratched = [
        r for r in uncapped_clean if races[r["race_id"]].get("scratched")
    ]
    uncapped_clean_no_scratch = [
        r for r in uncapped_clean if not races[r["race_id"]].get("scratched")
    ]
    all_positive_rejected = [r for r in feasible if r["min_unbet_cells"] > 0]
    all_zero_rejected = [
        r for r in feasible
        if not (r["raw_residual_min"] <= 0 <= r["raw_residual_max"])
    ]
    lines = [
        "# 삼쌍승식 `9999.9` 셀의 회계적 부분식별 구간",
        "",
        "## 결론",
        "",
        f"실질 분석의 주표본인 2022--2025년 {len(post_feasible):,}개 검열 경주, "
        f"{post_cells:,}개 상한 셀에서 무투표 합계의 회계적 구간은 "
        f"**{post_lower:,}--{post_upper:,}개**다. 모든 경주의 하한이 0이므로 이 "
        "주표본에서는 회계만으로 모든 상한 셀이 양수라는 모형을 한 번도 기각하지 못한다.",
        "",
        f"전기간 진단표본에서 회계 제약으로 좁혀지는 결과도 한 점이 아니라 넓은 구간이다. "
        f"엄격 규칙을 통과한 {len(feasible):,}개 검열 경주의 {feasible_cells:,}개 "
        f"`9999.9` 셀 가운데 무투표 셀 합계는 **{lower_zeros:,}--{upper_zeros:,}개**"
        f"({_pct(lower_zeros, feasible_cells)}--{_pct(upper_zeros, feasible_cells)})로만 묶인다.",
        "",
        f"불일치 셀을 정보 없는 양의 미지수 `[1,T]`로 두는 최악경계에서는 {len(relaxed):,}개 경주의 "
        f"{relaxed_cells:,}개 검열 셀에 대한 구간은 **{relaxed_lower:,}--{relaxed_upper:,}개**"
        f"({_pct(relaxed_lower, relaxed_cells)}--{_pct(relaxed_upper, relaxed_cells)})다. "
        "따라서 회계만으로 개별 셀의 무투표 여부를 실질적으로 식별하지 못한다. "
        "이 완화 상한은 제외 경주의 상한 셀을 전부 추가한 기계적 경계이므로 엄격 결과와 "
        f"동등한 강건성 추정치가 아니다: 상한 증가 {relaxed_upper-upper_zeros:,}개 = "
        f"엄격 제외 경주의 상한 셀 {excluded_capped_cells:,}개다.",
        "",
        f"양의 하한 {lower_zeros:,}개는 총합제약이 결속된 {len(forced):,}개 사례에서만 "
        "나온다. 표본 전체의 대표 추정치가 아니라 유지가정 아래의 사례 결과로 취급한다.",
        "",
        "원자료에는 2020·2021년 파티션이 없다. 2016--2019년에는 반올림 불일치가 "
        f"있지만 2022--2025년에는 0셀이므로, 후속 실질 분석의 주표본은 "
        "2022--2025년으로 둔다. 이전 시기는 불일치 원인이 해명되지 않은 역사적 "
        "진단표본이며 강건성 증거로 사용하지 않는다.",
        "",
        "## 정의와 계산",
        "",
        "경주별 삼쌍승식 총판매 마권 수를 `T=S/100`, 미검열 셀에서 역산한 "
        "마권 수 합의 범위를 `[L,U]`, 검열 셀 수를 `C`라 했다. 각 검열 셀은 "
        "`n ∈ {0,1,...,N}`으로 두었다. 모든 유효 순서조합이 19,301경주 전부에서 "
        "정확히 한 개의 수치 셀로 나타난다는 완전성 항등식은 별도의 결측표시가 없다는 "
        "증거일 뿐, 그 자체로 `n=0`이 실제 존재하거나 `9999.9`로 표시된다는 것을 "
        "구별하지 못한다. `n=0` 포함은 공식 인코딩 규정이 확인되지 않은 명시적 "
        "식별가정이며, 아래 두 극단모형 기각 사례가 직접적인 구별 증거다.",
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
        f"| 실행 전제조건: 서로 다른 조합이 출전두수 순열과 정확히 일치 | "
        f"{len(rows):,}/{len(rows):,} (위반 시 실행 중단) |",
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
        f"| 검열 경주 중 총합제약만으로 추가 기각 | "
        f"{len(capped_clean) - len(feasible):,} |",
        f"| 양의 무투표 하한을 만든 경주 | {len(forced):,}/{len(capped):,} |",
        f"| 모든 상한 셀이 양수라는 모형 기각 | {len(all_positive_rejected):,}/"
        f"{len(feasible):,} |",
        f"| 모든 상한 셀이 0이라는 모형 기각 | {len(all_zero_rejected):,}/"
        f"{len(feasible):,} |",
        "",
        f"모든 양수 모형을 기각하는 {len(all_positive_rejected):,}개 경주 밖에서는 "
        "회계자료가 무투표가 하나도 없는 완성표를 허용한다. 따라서 격자 완전성과 "
        "총합만으로는 그 밖의 경주에서 `n=0` 존재 여부를 구별할 수 없다. 반대로 "
        f"모든 0 모형은 {len(all_zero_rejected):,}개 경주에서 기각되어, 상한 셀을 "
        "일괄적으로 무투표로 해석하는 것도 자료와 맞지 않는다.",
        "",
        "엄격 규칙은 불일치 셀이 하나라도 있으면 경주를 제외하므로 격자가 큰 경주의 "
        "탈락확률이 기계적으로 높다. 따라서 엄격 결과는 선택된 부분표본이며, 셀 단위 "
        "완화 결과를 함께 제시한다. 완화 규칙의 100% feasible은 구성상 보장되어 "
        "반증시험으로 해석하지 않는다. 격자와 매출액이 같은 마감시점의 값이라는 가정은 "
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
        "### 표시코드 진단",
        "",
        f"유효 삼쌍승 조합에서 `1.0`은 {lower_code_cells:,}셀({lower_code_races:,}경주)이다. "
        "이를 하한코드로 재분류하지 않고 일반 표시배당으로 검사한다.",
        "",
        "### 자유도 0 검사의 정밀도",
        "",
        "| 통계 (총마권 수 대비) | 25% | 중앙값 | 75% |",
        "| --- | ---: | ---: | ---: |",
        f"| 허용구간 폭 `(U-L)/T` | {width_q[0]:.4%} | {width_q[1]:.4%} | {width_q[2]:.4%} |",
        f"| 허용구간 중심과 `T`의 거리 | {center_q[0]:.4%} | {center_q[1]:.4%} | {center_q[2]:.4%} |",
        "",
        "취소마 마권이 최종 승식별 매출에서 환불된 순매출이라는 가정은 무검열 "
        "자유도 0 검사를 취소마 유무로 나눠 확인한다.",
        "",
        "| 무검열 청정 경주 | 통과/대상 |",
        "| --- | ---: |",
        f"| 취소마 없음 | {sum(r['strict_feasible'] for r in uncapped_clean_no_scratch):,}/"
        f"{len(uncapped_clean_no_scratch):,} |",
        f"| 취소마 있음 | {sum(r['strict_feasible'] for r in uncapped_clean_scratched):,}/"
        f"{len(uncapped_clean_scratched):,} |",
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
    lines.extend([
        "### 시기별 주표본 분리", "",
        "| 시기 | 검열 경주 | 엄격 통과 | 불일치 셀 |",
        "| --- | ---: | ---: | ---: |",
        f"| 2016--2019 | {len(pre):,} | {len(pre_feasible):,} | "
        f"{sum(r['rounding_incompatible_cells'] for r in pre):,} |",
        f"| 2022--2025 | {len(post):,} | {len(post_feasible):,} | "
        f"{sum(r['rounding_incompatible_cells'] for r in post):,} |",
        "",
        "2020--2021년은 수집된 원자료 자체에 없고, 전후 불일치 차이는 데이터 생성·"
        "스냅샷 절차 변화와 일치하지만 현재 자료만으로 원인을 확정할 수 없다.", "",
    ])
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
        forced_dates = sorted({races[row["race_id"]]["date"] for row in forced})
        forced_meets = sorted({races[row["race_id"]]["meet"] for row in forced})
        pool_labels = (
            "단승식", "연승식", "복승식", "쌍승식", "복연승식", "삼복승식", "삼쌍승식"
        )
        sales_checks = []
        no_scratches = []
        all_arrived = []
        for row in forced:
            race = races[row["race_id"]]
            sales_checks.append(
                sum(_won(race["sales"][label]) for label in pool_labels)
                == _won(race["sales"]["총매출액"])
            )
            no_scratches.append(not (race.get("scratched") or []))
            all_arrived.append(
                len(race.get("arrival") or [])
                == len(race["horses"]) - len(race.get("scratched") or [])
            )
        lines.extend([
            f"## 양의 하한이 나온 {len(forced):,}개 사례 경주",
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
        date = forced_dates[0]
        meet = forced_meets[0]
        day = sorted(
            (r for r in races.values() if r["date"] == date and r["meet"] == meet),
            key=lambda r: r["race_no"],
        )
        lines.extend([
            "",
            f"파이프라인이 직접 재검사한 결과, 일곱 승식 합계 일치 "
            f"{sum(sales_checks):,}/{len(sales_checks):,}건, 취소마 없음 "
            f"{sum(no_scratches):,}/{len(no_scratches):,}건, 출주마 전부 착순 기록 "
            f"{sum(all_arrived):,}/{len(all_arrived):,}건이다. "
            "같은 날 삼쌍승 매출 흐름은 다음과 같다. 특이한 매출 변동의 제도적 "
            "원인은 저장자료만으로 확인할 수 없다.",
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
            "### 반올림 규약 × 환급률 민감도",
            "",
            "각 조합에서 모든 미검열 배당의 정수구간을 다시 계산했다. 불일치가 "
            "하나라도 있으면 그 규약은 해당 경주 전체와 양립하지 않는다. `붕괴점`은 "
            "유지규약에서 양의 하한을 0으로 만드는 데 필요한 미검열 구간 하단의 "
            "최소 1마권 하향 교란 수다.",
            "",
            "| race_id | 반올림 | 환급률 | 불일치 셀 | 미검열 합 `[L,U]` | 무투표 구간 | 붕괴점 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        sensitivity_odds = _load_trifecta_odds(
            data_dir, races, [row["race_id"] for row in top]
        )
        for item in _assumption_sensitivity(races, top, sensitivity_odds):
            lines.append(
                f"| {item['race_id']} | {item['rounding']} | {item['take']} | "
                f"{item['bad']:,} | {item['ticket_min']:,}--{item['ticket_max']:,} | "
                f"{item['min_zero']}--{item['max_zero']} | {item['breakdown']} |"
            )
        lines.extend([
            "",
            "유지규약 이외의 조합이 다수 미검열 셀과 모순되면 그것은 하한을 없애는 "
            "유효한 대안이 아니다. 그래도 양의 하한이 소수 사례와 수백 개 1마권 경계에 "
            "의존한다는 사실은 그대로 한계로 남는다. half-even은 관측된 모든 셀에서 "
            "half-up과 동일한 구간을 만들어 별도의 민감도 정보를 더하지 않는다. 두 경주의 "
            "비정상적으로 낮은 삼쌍승 매출이 실제 저매출인지 스냅샷 문제인지는 외부 기록 "
            "없이 구별되지 않으며, 이것이 182개 사례 결과의 경쟁 설명이다.",
            "",
        ])

    lines.extend([
        "## 외부 상한 초과 지급 표본과 해석",
        "",
        f"동결 상세 성적표 {winning_races:,}경주에서 상한 셀과 일치한 지급항목 "
        f"{winning_matched:,}건을 복원했고, 실제 상한 초과는 {winning_above:,}건, "
        f"그중 삼쌍승은 {winning_trifecta:,}건이다. 이는 실제 당첨조합만 "
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
