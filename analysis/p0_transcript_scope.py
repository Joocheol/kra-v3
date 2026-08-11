#!/usr/bin/env python3
"""How many cells does SPEC_P0 4.3(b) actually ask a person to transcribe?

MEASUREMENT ONLY. This does not change the spec. 4.3(b) fixes the comparison
target as "각 경주에서 7개 풀 전부, 각 풀의 셀 전수" over 5 races, but nobody
has counted what that comes to. The answer decides whether 4.3(b) is a
procedure or a wish.

Two counts per pool, because "셀 전수" is ambiguous and the difference is large:

  displayed  every odds cell the KRA grid actually prints, including the same
             trio repeated on several 고정마 pages. This is what a person
             reading screens would face, and it is what the comparison
             coordinate (page_key, page_variant, row_header, col_header)
             addresses.
  distinct   one cell per betting combination. Redundant printings collapse.

The gap between them is entirely 삼복승: each trio {a,b,c} is printed on three
fixed-horse pages, so displayed = 3 x distinct. 삼쌍승 has no redundancy —
each ordered triple appears once, on the page keyed by its 1st-place horse.

Usage:
    python3 analysis/p0_transcript_scope.py --archive <path> --sample outputs/p0/sample_38.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import sys
from math import comb

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from p0_probe import TABLE_RE, TD_RE, TR_RE, text  # noqa: E402


def grid_cells(page_html: str) -> int:
    """Odds cells actually printed in a page's grid.

    Counts cells that carry a payout, a censoring point or a scratch marker —
    i.e. what a transcriber would have to read and write down. Excludes the
    title row, the pool header, the 1..14 column header, the horse-number
    column, the diagonal, structural blanks ('-') and the sales-total row.
    """
    m = TABLE_RE.search(page_html)
    if not m:
        return 0
    n = 0
    for tr in TR_RE.findall(m.group(0)):
        cells = [text(c) for c in TD_RE.findall(tr)]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        if cells == [str(i + 1) for i in range(len(cells))]:
            continue                                    # column header row
        for j, v in enumerate(cells):
            if j == 0:
                continue                                # row's horse number
            if not v or set(v) <= {"-"} and len(v) < 3:
                continue                                # structural blank
            if v.isdigit() and v == cells[0]:
                continue                                # diagonal repeat
            n += 1
    return n


def scm_pool_cells(scm_html: str, n: int) -> tuple[int, int, int]:
    """(단승, 연승, 복승) cells on the Scm page.

    Scm needs its own counter: its data rows start with the 단승 payout
    ('7.2'), not with the horse number, so the generic grid reader skips them.
    Layout is r[0]=단승, r[1]=연승, r[2]=마번, r[3:]=복승 columns whose
    diagonal repeats the horse number.
    """
    m = TABLE_RE.search(scm_html)
    if not m:
        return 0, 0, 0
    win = place = quinella = 0
    for tr in TR_RE.findall(m.group(0)):
        cells = [text(c) for c in TD_RE.findall(tr)]
        if len(cells) < 4 or not cells[2].isdigit():
            continue
        if cells == [str(i + 1) for i in range(len(cells))]:
            continue                                    # column header row
        horse = cells[2]
        win += 1
        place += 1
        for v in cells[3:]:
            if not v or (set(v) <= {"-"} and len(v) < 3):
                continue                                # structural blank
            if v == horse:
                continue                                # diagonal repeat
            quinella += 1
    return win, place, quinella


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True, type=pathlib.Path)
    ap.add_argument("--sample", required=True, type=pathlib.Path)
    args = ap.parse_args()

    spec = json.loads(args.sample.read_text(encoding="utf-8"))
    targets = spec["transcript_5"]
    by_id = {r["race_id"]: r for r in spec["sample"]}
    index = {p.name.replace(".json.gz", ""): p
             for p in args.archive.rglob("*.json.gz")}

    print(f"{'race_id':<18} {'N':>3} {'장':>3} {'단':>4} {'연':>4} {'복':>5} "
          f"{'복연':>5} {'쌍':>6} {'삼복':>7} {'삼쌍':>7} {'합계':>8}")
    print("-" * 80)

    grand_disp = grand_dist = grand_sheets = 0
    for rid in targets:
        f = index.get(rid)
        if f is None:
            print(f"{rid:<18} 파일 없음")
            continue
        d = json.loads(gzip.decompress(f.read_bytes()))
        pages = d["pages"]
        n = by_id[rid]["n_registered"]

        win, place, quinella = scm_pool_cells(pages["Scm"], n)
        qplace = grid_cells(pages["Bc"])
        exacta = grid_cells(pages["Both"])
        trio = sum(grid_cells(v) for k, v in pages["3Bc"].items() if k != "_probe")
        trifecta = sum(grid_cells(v) for k, v in pages["3Both"].items() if k != "_probe")

        disp = win + place + quinella + qplace + exacta + trio + trifecta
        dist = win + place + comb(n, 2) * 2 + n * (n - 1) + comb(n, 3) + \
            n * (n - 1) * (n - 2)
        # pages a transcriber must open: Scm + Both + Bc + one 3Bc and one
        # 3Both per fixed horse. '_probe' is excluded — SPEC_P0 1 records it as
        # byte-identical to page '1', so it is the same screen twice.
        n_3bc = len([k for k in pages["3Bc"] if k != "_probe"])
        n_3both = len([k for k in pages["3Both"] if k != "_probe"])
        sheets = 3 + n_3bc + n_3both
        grand_disp += disp
        grand_dist += dist
        grand_sheets += sheets
        print(f"{rid:<18} {n:>3} {sheets:>3} {win:>4} {place:>4} {quinella:>5} "
              f"{qplace:>5} {exacta:>6} {trio:>7} {trifecta:>7} {disp:>8,}")

    print("-" * 80)
    print(f"{'열어야 할 페이지 (5경주)':<40} {grand_sheets:>8,}")
    print(f"{'표시 셀 합계 (5경주)':<40} {grand_disp:>8,}")
    print(f"{'조합 기준 합계 (중복 제거)':<38} {grand_dist:>8,}")
    print()
    # Rates are seconds PER CELL. Careful transcription of a number from a
    # screen into a sheet, with the eye returning to the right row, is not a
    # once-per-second operation; 2s is optimistic and 5s is unhurried.
    print("  사람이 눈으로 읽고 타이핑할 때 (표시 셀 기준)")
    for sec in (2, 3, 5):
        hrs = grand_disp * sec / 3600
        print(f"    셀당 {sec}초 → {hrs:5.1f} 시간 ({hrs/6:.1f} 사람-일, "
              f"하루 6시간 집중 기준)")

    # The count depends steeply on field size, so "5 races" does not bound the
    # work to within a factor of three. Show the spread over the whole 38.
    sizes = sorted(r["n_registered"] for r in spec["sample"])
    print()
    print("  경주당 표시 셀은 등록두수에 급격히 의존한다 (닫힌 식)")
    for n in (7, 10, 12, 14, 16):
        print(f"    {n:>2}두 → {displayed_formula(n):>6,} 셀")
    lo, hi = sizes[0], sizes[-1]
    print(f"  표본 38경주의 등록두수 범위 {lo}–{hi}두 → "
          f"경주당 {displayed_formula(lo):,}–{displayed_formula(hi):,} 셀 "
          f"({displayed_formula(hi)/displayed_formula(lo):.1f}배)")


def displayed_formula(n: int) -> int:
    """Displayed odds cells for a field of n, closed form.

    2n (단승+연승) + 2C(n,2) (복승+복연승) + n(n-1) (쌍승)
    + 3C(n,3) (삼복승, each trio printed on three 고정마 pages)
    + n(n-1)(n-2) (삼쌍승)

    Verified against the archive counts printed above.
    """
    return (2 * n + 2 * comb(n, 2) + n * (n - 1)
            + 3 * comb(n, 3) + n * (n - 1) * (n - 2))


if __name__ == "__main__":
    main()
