#!/usr/bin/env python3
"""Print one parsed race, rebuilding each page's grid from the cell rows.

    python3 show_race.py 2018-05-04_2_03
    python3 show_race.py 2018-05-04_2_03 --page Both --page 3Bc --variant 1

Redrawing the table out of `(row_header, col_header)` is the point: if the
coordinates are right the output looks like the page it came from, and if a
column is off by one it shows up immediately as a shifted diagonal.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import pathlib
import sys

PAGE_ORDER = ["Scm", "Both", "Bc", "3Bc", "3Both"]


def load_race(out: pathlib.Path, race_id: str) -> dict:
    with gzip.open(out / "races.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["race_id"] == race_id:
                return r
    sys.exit(f"{race_id} not in {out}/races.jsonl.gz")


def load_cells(out: pathlib.Path, race_id: str, page_key: str) -> list[dict]:
    month = race_id[:7]
    p = out / "cells" / f"page_key={page_key}" / f"{month}.csv.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["race_id"] == race_id]


def draw(cells: list[dict], title: str, variant: str = "") -> None:
    body = [c for c in cells
            if c["section"] == "body" and c["page_variant"] == variant
            and c["row_header"] and c["col_header"]]
    if not body:
        return
    rows = sorted({c["row_header"] for c in body}, key=lambda x: int(x))
    # keep the printed column order, numeric columns after the named ones
    named = [c for c in dict.fromkeys(x["col_header"] for x in body)
             if not c.isdigit()]
    nums = sorted({c["col_header"] for c in body if c["col_header"].isdigit()},
                  key=int)
    cols = named + nums
    grid = {(c["row_header"], c["col_header"]): c["cell_raw"] for c in body}
    groups = {c["col_header"]: c["col_group"] for c in body}

    w = max(7, max((len(v) for v in grid.values()), default=4) + 1)
    print(f"\n  {title}")
    # Group headers carry the axis semantics -- "( 후착 / 선착 )" says which
    # way round the exacta grid reads -- so print them in full as a legend
    # rather than squeezing them into a column width.
    legend, seen = [], set()
    for c in cols:
        g = groups.get(c, "")
        if g and g not in seen and g != c:
            seen.add(g)
            span = [x for x in cols if groups.get(x) == g]
            legend.append(f"{g} → {span[0]}‥{span[-1]}" if len(span) > 1 else g)
    if legend:
        print("    열 그룹: " + " | ".join(legend))
    print(" " * 5 + "".join(c.rjust(w) for c in cols))
    for r in rows:
        print(f"{r:>4} " + "".join(grid.get((r, c), "").rjust(w) for c in cols))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("race_id")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("outputs/parsed"))
    ap.add_argument("--page", action="append", default=None,
                    help="page key to draw (repeatable); default Scm")
    ap.add_argument("--variant", default="",
                    help="fixed-horse page for 3Bc/3Both")
    args = ap.parse_args()

    r = load_race(args.out, args.race_id)
    print(f"{r['race_id']}   {r['meet_name']} {r['race_no']}R   {r['date']}")
    print(f"  등록 {r['n_registered']}두  {r['horses']}")
    print(f"  도착 {r['n_arrival']}두  {r['arrival']}")
    if r["scratched"]:
        print(f"  취소마 {r['scratched']}   공지 {r['cancel_notice']!r}")
    else:
        print(f"  취소마 없음   공지 {r['cancel_notice']!r}")
    print(f"  매출  " + "  ".join(f"{k} {v}" for k, v in r["sales"].items()))
    print(f"  페이지 {r['pages']}")
    if r["problems"]:
        print(f"  문제 {r['problems']}")

    for pk in (args.page or ["Scm"]):
        cells = load_cells(args.out, args.race_id, pk)
        v = args.variant if pk in ("3Bc", "3Both") else ""
        label = f"{pk}" + (f"  (고정마 {v})" if v else "")
        draw(cells, label, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
