#!/usr/bin/env python3
"""Fail-fast validation for grids consumed by ``analyze_cross_market.py``.

The legacy ``check_coherence.load_month`` loader predates the strict trifecta
loader and writes mapped cells into dictionaries. This preflight verifies that,
for the 2022--2025 substantive sample, the weaker code path cannot silently
lose information through spanned numeric cells, conflicting duplicate mapped
keys, missing active-horse combinations, or extra combinations. Identical
redundant displays are counted but are harmless because dictionary overwrite
preserves the same observed value.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import itertools
import json
import pathlib
from collections import defaultdict

from check_coherence import to_odds

PAGE_KEYS = ("Scm", "Both", "Bc", "3Bc", "3Both")
TARGETS = ("win", "quinella", "exacta", "trio", "trifecta")


def load_races(path: pathlib.Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            race = json.loads(line)
            if "2022" <= race["date"][:4] <= "2025":
                out[race["race_id"]] = race
    return out


def mapped_key(pk: str, row: dict[str, str]):
    rh, ch = row["row_header"], row["col_header"]
    if not rh.isdigit():
        return None
    i = int(rh)
    if pk == "Scm":
        group = row["col_group"]
        if group == "단승식":
            return "win", i
        if group == "복승식" and ch.isdigit() and int(ch) != i:
            return "quinella", frozenset((i, int(ch)))
        return None
    if pk == "Both" and ch.isdigit() and int(ch) != i:
        return "exacta", (int(ch), i)
    if pk == "3Bc" and ch.isdigit() and row["page_variant"].isdigit():
        combo = frozenset((int(row["page_variant"]), i, int(ch)))
        if len(combo) == 3:
            return "trio", combo
        return None
    if pk == "3Both" and ch.isdigit() and row["page_variant"].isdigit():
        a = int(row["page_variant"])
        if len({a, i, int(ch)}) == 3:
            return "trifecta", (a, int(ch), i)
        return None
    return None


def validate(data_dir: pathlib.Path) -> dict[str, int]:
    races = load_races(data_dir / "races.jsonl.gz")
    months = sorted({race["date"][:7] for race in races.values()})
    seen: dict[str, dict[str, dict[object, str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    numeric_rows = spanned_numeric = duplicate_rows = conflicting_duplicates = 0

    for month in months:
        for pk in PAGE_KEYS:
            path = data_dir / "cells" / f"page_key={pk}" / f"{month}.csv.gz"
            if not path.exists():
                raise FileNotFoundError(path)
            with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    race_id = row["race_id"]
                    if race_id not in races or row["section"] != "body":
                        continue
                    if to_odds(row["cell_raw"]) is None:
                        continue
                    numeric_rows += 1
                    if row.get("spanned", "0") != "0":
                        spanned_numeric += 1
                        raise ValueError(
                            f"{race_id}: {pk} contains numeric spanned cell "
                            f"({row['row_header']}, {row['col_header']})"
                        )
                    mapped = mapped_key(pk, row)
                    if mapped is None:
                        continue
                    target, key = mapped
                    prior = seen[race_id][target].get(key)
                    if prior is not None:
                        duplicate_rows += 1
                        if prior != row["cell_raw"]:
                            conflicting_duplicates += 1
                            raise ValueError(
                                f"{race_id}: conflicting duplicate {target} key {key!r}: "
                                f"{prior!r} vs {row['cell_raw']!r}"
                            )
                        continue
                    seen[race_id][target][key] = row["cell_raw"]

    checked = 0
    for race_id, race in races.items():
        active = sorted(set(race["horses"]) - set(race.get("scratched") or []))
        expected = {
            "win": set(active),
            "quinella": {frozenset(x) for x in itertools.combinations(active, 2)},
            "exacta": set(itertools.permutations(active, 2)),
            "trio": {frozenset(x) for x in itertools.combinations(active, 3)},
            "trifecta": set(itertools.permutations(active, 3)),
        }
        for target in TARGETS:
            actual = set(seen[race_id][target])
            if actual != expected[target]:
                missing = len(expected[target] - actual)
                extra = len(actual - expected[target])
                raise ValueError(
                    f"{race_id}: invalid {target} support; missing={missing}, extra={extra}"
                )
        checked += 1

    result = {
        "races": checked,
        "numeric_rows": numeric_rows,
        "spanned_numeric": spanned_numeric,
        "duplicate_rows": duplicate_rows,
        "conflicting_duplicates": conflicting_duplicates,
    }
    print("CROSS_MARKET_PREFLIGHT " + json.dumps(result, sort_keys=True))
    return result


def make_report(result: dict[str, int]) -> str:
    return "\n".join([
        "# 교차시장 분석 입력 격자 검증",
        "",
        "## 목적",
        "",
        "교차시장 분석은 기존 `check_coherence.load_month` 로더를 사용한다. 이 로더는 "
        "딕셔너리로 셀을 적재하므로, 병합(spanned) 숫자 셀이나 서로 다른 값의 중복 "
        "키가 있으면 조용히 덮어쓸 위험이 있다. 2022--2025년 실질 분석 표본에 대해 "
        "원시 셀을 다시 읽어 이런 경로가 실제로 존재하는지 전수 검사한다.",
        "",
        "## 결과",
        "",
        "| 항목 | 결과 |",
        "| --- | ---: |",
        f"| 검증 경주 | {result['races']:,} |",
        f"| 읽은 숫자 셀 행 | {result['numeric_rows']:,} |",
        f"| 동일값 중복 행 | {result['duplicate_rows']:,} |",
        f"| 서로 다른 값의 충돌 중복 | {result['conflicting_duplicates']:,} |",
        f"| 숫자 spanned 셀 | {result['spanned_numeric']:,} |",
        "| 단승·복승·쌍승·삼복승·삼쌍승 활성마 조합 support | 전 경주 완전 일치 |",
        "",
        "동일값 중복은 같은 조합이 여러 위치에 반복 표기된 경우이며 딕셔너리 덮어쓰기가 "
        "값을 바꾸지 않는다. 서로 다른 값의 충돌 중복은 0건이고 숫자 spanned 셀도 "
        "0건이다. 또한 다섯 대상 시장의 매핑된 조합 집합이 각 경주의 취소마를 제외한 "
        "활성마에서 계산한 이론 support와 전부 일치했다.",
        "",
        "이 검사는 행·열 의미 자체의 외부 진실을 증명하지 않는다. 그 방향성은 상세 "
        "지급표, 페이지 표제, 2·3착 축 반전 반증모형으로 별도 검증한다. 여기서 확인한 "
        "것은 현재 2022--2025 표본에서 약한 로더가 spanned/충돌중복/누락 때문에 "
        "조용히 가격표를 바꾸는 경로가 없다는 점이다.",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/cross_market_input_validation.md"),
    )
    args = parser.parse_args()
    result = validate(args.data_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(make_report(result), encoding="utf-8")
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
