#!/usr/bin/env python3
"""Check the parsed output. Exits non-zero if anything is wrong.

    python3 check_parsed.py --out 데이터
    python3 check_parsed.py --out 데이터 --archive <path>   # adds _probe check

A parser that only agrees with itself proves nothing, so the checks below fall
into three kinds, in increasing order of how much they can catch:

1. **Against an independent reading.** Figures measured on this same archive
   by a regex reader rather than `html.parser`. Two implementations landing on
   the same count is the point.
2. **Structural identities.** Things that must hold whatever the parser does --
   a trio printed on three pages must carry one value, a grid must be
   rectangular, horse numbers must run 1..N.
3. **Leakage.** Markup or entities surviving into a cell mean the extraction
   silently failed on that cell rather than raising.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import pathlib
import re
import sys

THETA = "9999.9"
PAGE_KEYS = ["Scm", "Both", "Bc", "3Bc", "3Both"]
FIXED_HORSE_PAGES = ["3Bc", "3Both"]

# Independently measured on the same archive (regex reader, earlier pass).
EXPECTED = {
    "races": 19301,
    "both_theta_cells": 2594,
    "both_theta_races": 581,
    "cancel_agree": 2163,
    "cancel_disagree": 20,
}

TAG = re.compile(r"<[^>]+>")
ENTITY = re.compile(r"&(?:[a-zA-Z]+|#\d+);")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_fail: list[str] = []


def check(name: str, got, want, note: str = "") -> None:
    ok = got == want
    print(f"  [{'OK  ' if ok else '다름'}] {name:<44} {got!s:>12}  기대 {want!s}"
          + (f"   {note}" if note else ""))
    if not ok:
        _fail.append(name)


def load_races(out: pathlib.Path) -> list[dict]:
    p = out / "races.jsonl.gz"
    if not p.exists():
        sys.exit(f"missing {p} -- run parse_archive.py first")
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def cell_files(out: pathlib.Path, page_key: str) -> list[pathlib.Path]:
    d = out / "cells" / f"page_key={page_key}"
    return sorted(d.glob("*.csv.gz")) if d.is_dir() else []


def iter_cells(out: pathlib.Path, page_key: str):
    for p in cell_files(out, page_key):
        with gzip.open(p, "rt", encoding="utf-8", newline="") as fh:
            yield from csv.DictReader(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("데이터"))
    ap.add_argument("--archive", type=pathlib.Path,
                    help="raw archive; enables the _probe duplication check")
    ap.add_argument("--quick", action="store_true", help="skip cell-level checks")
    args = ap.parse_args()

    races = load_races(args.out)
    by_id = {r["race_id"]: r for r in races}

    print("\n=== 1. 독립 측정치와의 대조 ===")
    check("경주 수", len(races), EXPECTED["races"])
    agree = disagree = 0
    for r in races:
        declared = bool(r["cancel_notice"]) and "없습니다" not in r["cancel_notice"]
        if declared and r["scratched"]:
            agree += 1
        elif declared != bool(r["scratched"]):
            disagree += 1
    check("취소마 두 신호 일치", agree, EXPECTED["cancel_agree"])
    check("취소마 두 신호 불일치", disagree, EXPECTED["cancel_disagree"])

    print("\n=== 2. 경주 단위 구조 ===")
    bad_pages, bad_seq, bad_subset, bad_arr = [], [], [], []
    for r in races:
        n = r["n_registered"]
        for pk in FIXED_HORSE_PAGES:
            if r["pages"].get(pk, 0) != n:
                bad_pages.append((r["race_id"], pk))
        for pk in ("Scm", "Both", "Bc"):
            if r["pages"].get(pk, 0) != 1:
                bad_pages.append((r["race_id"], pk))
        if r["horses"] != list(range(1, n + 1)):
            bad_seq.append(r["race_id"])
        if not set(r["arrival"]) <= set(r["horses"]):
            bad_subset.append(r["race_id"])
        if len(r["arrival"]) != len(set(r["arrival"])):
            bad_arr.append(r["race_id"])
    check("페이지 구성 (단일 1장, 고정마 N장)", len(bad_pages), 0)
    check("마번이 1..N 연속", len(bad_seq), 0)
    check("도착마번 ⊆ 등록마번", len(bad_subset), 0)
    check("도착마번 중복 없음", len(bad_arr), 0)
    for lst, lab in ((bad_pages, "페이지"), (bad_seq, "마번"), (bad_subset, "도착")):
        if lst:
            print(f"        {lab} 위반 예: {lst[:3]}")

    print("\n=== 3. 파싱 실패 ===")
    probs = args.out / "problems.jsonl"
    lines = probs.read_text(encoding="utf-8").splitlines() if probs.exists() else []
    check("problems.jsonl 줄 수", len(lines), 0)
    for line in lines[:5]:
        print(f"        {line[:160]}")

    if args.quick:
        print("\n(셀 검사 생략)")
        return 1 if _fail else 0

    print("\n=== 4. 셀 무결성 (전 페이지) ===")
    leaked_tag = leaked_ent = leaked_ctl = 0
    missing_hdr: collections.Counter = collections.Counter()
    grid_rows: dict = collections.defaultdict(lambda: collections.defaultdict(set))
    grid_cols: dict = collections.defaultdict(lambda: collections.defaultdict(set))
    grid_n: dict = collections.defaultdict(collections.Counter)
    n_cells = collections.Counter()
    theta_cells = 0
    theta_races: set[str] = set()
    trio: dict = collections.defaultdict(dict)

    for pk in PAGE_KEYS:
        if not cell_files(args.out, pk):
            _fail.append(f"{pk} 파티션 없음")
            print(f"  [다름] {pk} 파티션이 없다")
            continue
        for row in iter_cells(args.out, pk):
            n_cells[pk] += 1
            v = row["cell_raw"]
            if TAG.search(v):
                leaked_tag += 1
            if ENTITY.search(v):
                leaked_ent += 1
            if CONTROL.search(v):
                leaked_ctl += 1
            if row["section"] != "body":
                continue
            if not row["col_header"]:
                missing_hdr[pk] += 1
            rid, var = row["race_id"], row["page_variant"]
            if row["row_header"].isdigit() and row["col_header"].isdigit():
                key = (rid, var)
                grid_rows[pk][key].add(row["row_header"])
                grid_cols[pk][key].add(row["col_header"])
                grid_n[pk][key] += 1
                if pk == "Both" and v == THETA:
                    theta_cells += 1
                    theta_races.add(rid)
                if pk == "3Bc" and v not in ("-", ""):
                    a, b, c = int(var), int(row["row_header"]), int(row["col_header"])
                    if len({a, b, c}) == 3:
                        trio[rid].setdefault(frozenset((a, b, c)), {})[a] = v

    check("셀에 HTML 태그 잔존", leaked_tag, 0)
    check("셀에 미해독 엔티티 잔존", leaked_ent, 0)
    check("셀에 제어문자 잔존", leaked_ctl, 0)
    check("body 셀에 col_header 없음", sum(missing_hdr.values()), 0,
          str(dict(missing_hdr)) if missing_hdr else "")
    print(f"        셀 수: " + ", ".join(f"{k} {n_cells[k]:,}" for k in PAGE_KEYS))

    print("\n=== 5. 격자 형태 (페이지별) ===")
    for pk in PAGE_KEYS:
        bad = [k for k, n in grid_n[pk].items()
               if n != len(grid_rows[pk][k]) * len(grid_cols[pk][k])]
        check(f"{pk} 격자가 직사각형", len(bad), 0)
        bad_rows = [k for k, rs in grid_rows[pk].items()
                    if len(rs) != by_id[k[0]]["n_registered"]]
        check(f"{pk} 격자 행 수 = 등록두수", len(bad_rows), 0)
        if bad_rows:
            k = bad_rows[0]
            print(f"        예: {k} 행 {len(grid_rows[pk][k])}, "
                  f"등록 {by_id[k[0]]['n_registered']}두")

    print("\n=== 6. θ (독립 측정치) ===")
    check("쌍승 θ 셀", theta_cells, EXPECTED["both_theta_cells"])
    check("쌍승 θ 경주", len(theta_races), EXPECTED["both_theta_races"])

    print("\n=== 7. 페이지 간 교차 검증 (삼복승) ===")
    tot = agree3 = 0
    bad_trio = []
    for rid, combos in trio.items():
        for t, byfix in combos.items():
            tot += 1
            if len(byfix) == 3 and len(set(byfix.values())) == 1:
                agree3 += 1
            else:
                bad_trio.append((rid, sorted(t), byfix))
    check("삼복승 조합이 세 고정마 페이지에서 일치", len(bad_trio), 0,
          f"검사 {tot:,}조합")
    for b in bad_trio[:3]:
        print(f"        {b}")

    if args.archive:
        print("\n=== 8. _probe 가 page1 과 동일한가 (건너뛴 근거) ===")
        import random
        files = sorted(args.archive.rglob("*.json.gz"))
        rnd = random.Random(0)
        sample = rnd.sample(files, min(300, len(files)))
        diff = 0
        for f in sample:
            d = json.loads(gzip.decompress(f.read_bytes()))
            for pk in FIXED_HORSE_PAGES:
                p = d.get("pages", {}).get(pk)
                if isinstance(p, dict) and "_probe" in p and "1" in p:
                    if p["_probe"] != p["1"]:
                        diff += 1
        check("_probe != page1 인 경우", diff, 0, f"표본 {len(sample)}경주")

    print()
    if _fail:
        print(f"★ 실패 {len(_fail)}건: {_fail}")
        return 1
    print("전부 통과 — 오류 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
