#!/usr/bin/env python3
"""배당 값의 범위를 전수로 훑는다 — 특히 1.0 미만이 있는가.

    python3 scan_odds_range.py --out 데이터

파리뮤추얼 배당은 원금을 포함한 지급률이므로 1.0 미만이면 걸었던 돈보다 적게
돌려받는다는 뜻이다. 한국 마사회는 원금 보장(최저 1.0)이 있는 것으로 알려져
있어, 1.0 미만이 나온다면 둘 중 하나다 — 실제로 그런 값이 인쇄됐거나, 배당이
아닌 셀을 배당으로 잘못 읽고 있거나.

배당이 아닌 셀을 반드시 걸러야 한다. 격자에는 배당 말고도 숫자가 있다.

  - `출전 번호` 열      행의 마번. 1, 2, 3 …
  - 대각선              그 행의 마번을 되풀이한다
  - `<thead>`/`<tfoot>` 열 머리(1..16)와 매출액

이것들을 걸러내지 않으면 마번 1 이 배당 1.0 으로 둔갑한다.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import pathlib
import sys

PAGE_KEYS = ["Scm", "Both", "Bc", "3Bc", "3Both"]
# CellRow.FIELDS 순서
RACE_ID, PAGE_KEY, VARIANT, SECTION = 0, 1, 2, 3
ROW_HDR, COL_GROUP, COL_HDR, CELL_RAW = 6, 7, 8, 9

HORSE_COL = "출전 번호"


def is_odds_cell(r: list[str]) -> bool:
    """배당이 실릴 수 있는 셀인가."""
    if r[SECTION] != "body":
        return False
    if r[COL_GROUP] == HORSE_COL or r[COL_HDR] == HORSE_COL:
        return False                      # 마번 열
    if r[ROW_HDR] and r[ROW_HDR] == r[COL_HDR]:
        return False                      # 대각선
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("데이터"))
    ap.add_argument("--threshold", type=float, default=1.0)
    ap.add_argument("--dump", type=pathlib.Path,
                    default=pathlib.Path("outputs/odds_below_1.csv"))
    args = ap.parse_args()

    n_cells = collections.Counter()
    n_numeric = collections.Counter()
    below = collections.Counter()
    lo = {}                                # page_key -> (value, race, coords)
    hist = collections.Counter()
    found: list[list[str]] = []

    for pk in PAGE_KEYS:
        d = args.out / "cells" / f"page_key={pk}"
        files = sorted(d.glob("*.csv.gz"))
        if not files:
            sys.exit(f"no partitions for {pk}")
        print(f"  {pk}: {len(files)} 파티션", file=sys.stderr)
        for p in files:
            with gzip.open(p, "rt", encoding="utf-8", newline="") as fh:
                rd = csv.reader(fh)
                next(rd, None)
                for r in rd:
                    n_cells[pk] += 1
                    if not is_odds_cell(r):
                        continue
                    v = r[CELL_RAW]
                    try:
                        f = float(v)
                    except ValueError:
                        continue
                    n_numeric[pk] += 1
                    hist[_band(f)] += 1
                    if pk not in lo or f < lo[pk][0]:
                        lo[pk] = (f, r[RACE_ID], r[VARIANT], r[ROW_HDR], r[COL_HDR])
                    if f < args.threshold:
                        below[pk] += 1
                        if len(found) < 100000:
                            found.append(r)

    print("\n=== 셀 수 ===")
    for pk in PAGE_KEYS:
        print(f"  {pk:<6} 전체 {n_cells[pk]:>12,}   배당 후보 {n_numeric[pk]:>12,}")
    print(f"  {'합계':<6} 전체 {sum(n_cells.values()):>12,}"
          f"   배당 후보 {sum(n_numeric.values()):>12,}")

    print(f"\n=== {args.threshold} 미만 ===")
    total = sum(below.values())
    for pk in PAGE_KEYS:
        print(f"  {pk:<6} {below[pk]:>10,}")
    print(f"  {'합계':<6} {total:>10,}")

    print("\n=== 페이지별 최소 배당 ===")
    for pk in PAGE_KEYS:
        if pk in lo:
            f, rid, var, rh, ch = lo[pk]
            where = f"{rid} {rh}x{ch}" + (f" 고정마{var}" if var else "")
            print(f"  {pk:<6} {f:>10}   {where}")

    print("\n=== 배당 분포 ===")
    for b in ("<1.0", "1.0", "1.0~1.5", "1.5~2", "2~10", "10~100",
              "100~1000", "1000~9999.8", "9999.9(θ)", ">9999.9"):
        if hist[b]:
            print(f"  {b:<12} {hist[b]:>12,}")

    if found:
        args.dump.parent.mkdir(parents=True, exist_ok=True)
        with args.dump.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["race_id", "page_key", "page_variant", "section",
                        "row", "col", "row_header", "col_group", "col_header",
                        "cell_raw", "rowspan", "colspan", "spanned"])
            w.writerows(found)
        print(f"\n  wrote {args.dump}  ({len(found):,}행)")
    return 0


def _band(f: float) -> str:
    if f < 1.0:
        return "<1.0"
    if f == 1.0:
        return "1.0"
    if f < 1.5:
        return "1.0~1.5"
    if f < 2:
        return "1.5~2"
    if f < 10:
        return "2~10"
    if f < 100:
        return "10~100"
    if f < 1000:
        return "100~1000"
    if f < 9999.9:
        return "1000~9999.8"
    if f == 9999.9:
        return "9999.9(θ)"
    return ">9999.9"


if __name__ == "__main__":
    raise SystemExit(main())
