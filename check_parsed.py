#!/usr/bin/env python3
"""Check the parsed output against facts measured independently of it.

    python3 check_parsed.py --out outputs/parsed

A parser that only agrees with itself proves nothing, so every check below
compares the parsed tables against a number obtained some other way -- either
by a different reading of the same archive, or by a structural identity that
must hold whatever the parser does.

The reference figures come from earlier passes over this same archive using a
regex reader rather than `html.parser`. Two independent implementations
landing on the same count is the point; if this script disagrees with them,
one of the two readings is wrong and the difference has to be explained before
the output is used.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import pathlib
import sys
from math import comb

THETA = "9999.9"
SCRATCH_MIN_DASHES = 3

# Independently measured on the same archive (regex reader, earlier pass).
EXPECTED = {
    "races": 19301,
    "both_theta_cells": 2594,       # θ in the 쌍승 grid
    "both_theta_races": 581,
    "cancel_agree": 2163,           # notice declares a horse AND '----' present
    "cancel_disagree": 20,          # the two signals disagree
}


def load_races(out: pathlib.Path) -> list[dict]:
    path = out / "races.jsonl.gz"
    if not path.exists():
        sys.exit(f"missing {path} -- run parse_archive.py first")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def iter_cells(out: pathlib.Path, page_key: str):
    d = out / "cells" / f"page_key={page_key}"
    if not d.is_dir():
        return
    for p in sorted(d.glob("*.csv.gz")):
        with gzip.open(p, "rt", encoding="utf-8", newline="") as fh:
            yield from csv.DictReader(fh)


def check(name: str, got, want, note: str = "") -> bool:
    ok = got == want
    mark = "OK  " if ok else "다름"
    extra = f"   {note}" if note else ""
    print(f"  [{mark}] {name:<42} {got!s:>12}  기대 {want!s}{extra}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("outputs/parsed"))
    ap.add_argument("--skip-cells", action="store_true")
    args = ap.parse_args()

    races = load_races(args.out)
    by_id = {r["race_id"]: r for r in races}
    ok = True

    print("\n=== 1. 외부 측정치와의 대조 (다른 구현으로 얻은 수) ===")
    ok &= check("경주 수", len(races), EXPECTED["races"])

    agree = disagree = 0
    for r in races:
        declared = bool(r["cancel_notice"]) and "없습니다" not in r["cancel_notice"]
        dashed = bool(r["scratched"])
        if declared and dashed:
            agree += 1
        elif declared != dashed:
            disagree += 1
    ok &= check("취소마 두 신호 일치", agree, EXPECTED["cancel_agree"],
                "공지 선언 AND '----' 존재")
    ok &= check("취소마 두 신호 불일치", disagree, EXPECTED["cancel_disagree"])

    print("\n=== 2. 구조적 항등식 (파서와 무관하게 성립해야 하는 것) ===")
    bad_pages, bad_dup, bad_subset, bad_seq = [], [], [], []
    for r in races:
        n = r["n_registered"]
        # each fixed-horse page set must have exactly one page per horse
        for pk in ("3Bc", "3Both"):
            if r["pages"].get(pk, 0) != n:
                bad_pages.append((r["race_id"], pk, r["pages"].get(pk), n))
        if len(r["horses"]) != len(set(r["horses"])):
            bad_dup.append(r["race_id"])
        if r["horses"] != list(range(1, n + 1)):
            bad_seq.append(r["race_id"])
        if not set(r["arrival"]) <= set(r["horses"]):
            bad_subset.append(r["race_id"])
    ok &= check("등록두수 == 고정마 페이지 수", len(bad_pages), 0)
    ok &= check("마번 중복 없음", len(bad_dup), 0)
    ok &= check("마번이 1..N 연속", len(bad_seq), 0)
    ok &= check("도착마번 ⊆ 등록마번", len(bad_subset), 0)
    for lst, label in ((bad_pages, "페이지 수"), (bad_seq, "마번 연속"),
                       (bad_subset, "도착 부분집합")):
        if lst:
            print(f"        {label} 위반 예: {lst[:3]}")

    print("\n=== 3. 파싱 실패 ===")
    probs = args.out / "problems.jsonl"
    n_prob = sum(1 for _ in probs.open(encoding="utf-8")) if probs.exists() else 0
    ok &= check("problems.jsonl 줄 수", n_prob, 0)

    if args.skip_cells:
        print("\n(셀 검사 생략)")
        return 0 if ok else 1

    print("\n=== 4. 셀 대조 ===")
    theta_cells = 0
    theta_races: set[str] = set()
    grid_cells: collections.Counter = collections.Counter()
    cols_seen: dict[str, set[str]] = collections.defaultdict(set)
    rows_seen: dict[str, set[str]] = collections.defaultdict(set)
    for row in iter_cells(args.out, "Both"):
        if row["section"] != "body":
            continue
        if row["cell_raw"] == THETA:
            theta_cells += 1
            theta_races.add(row["race_id"])
        if row["col_header"].isdigit() and row["row_header"].isdigit():
            grid_cells[row["race_id"]] += 1
            cols_seen[row["race_id"]].add(row["col_header"])
            rows_seen[row["race_id"]].add(row["row_header"])
    ok &= check("쌍승 θ 셀", theta_cells, EXPECTED["both_theta_cells"])
    ok &= check("쌍승 θ 경주", len(theta_races), EXPECTED["both_theta_races"])

    # The grid is printed wider than the field: 14 columns for a field up to
    # 14, and 16 for the 80 races with 15 or 16 runners. The width is a
    # property of the page, so read it off the parsed headers instead of
    # assuming one -- an earlier version of this check hardcoded 14 and failed
    # on exactly those 80 races.
    bad_rows = [rid for rid, rs in rows_seen.items()
                if len(rs) != by_id[rid]["n_registered"]]
    ok &= check("쌍승 격자 행 수 = 등록두수", len(bad_rows), 0)

    bad_grid = [rid for rid, n in grid_cells.items()
                if n != len(rows_seen[rid]) * len(cols_seen[rid])]
    ok &= check("쌍승 격자가 직사각형 (행 x 열)", len(bad_grid), 0)
    if bad_grid:
        rid = bad_grid[0]
        print(f"        예: {rid} 관측 {grid_cells[rid]}, "
              f"{len(rows_seen[rid])}행 x {len(cols_seen[rid])}열")

    widths = collections.Counter(
        (by_id[rid]["n_registered"], len(cs)) for rid, cs in cols_seen.items())
    print("        인쇄 폭 (등록두수 -> 열수): "
          + ", ".join(f"{n}두→{w}열 ×{c:,}" for (n, w), c in sorted(widths.items())))

    print("\n" + ("전부 통과" if ok else "★ 불일치가 있다. 위 항목을 확인하라"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
