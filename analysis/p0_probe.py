#!/usr/bin/env python3
"""Measure what the archive's special tokens actually mean.

SPEC_P0 classifies 9999.9, '----' and '-' in L3, but the round-2 critique (K6)
observed that the spec never establishes what any of them denote. Reading the
meaning off the odds cells themselves would be circular: the parser rule under
test would supply its own warrant. Each probe below therefore takes its
evidence from a part of the page that the odds-cell rule does not touch.

  theta   9999.9 in the exacta (Both) grid, checked against the quinella-place
          (Bc) payout for the same unordered pair. Different page, different
          table, different pool. A pair that carries a normal Bc payout was
          bet on, so its exacta odds cannot be an 'undefined' marker.

  cancel  '----' runs, checked against the 취소마공지 row at the foot of the
          table. That row names horses; it is not an odds cell.

  dash    '-' singletons, located by position: lower triangle (duplicate
          combination) or beyond the field size (horse never entered).

  token   Free-text odds tokens such as the '1.5 취소' that SPEC_P0 2.1 and
          3.2(a) cite. Counts them across the archive.

Stdlib only, on purpose: this has to run before any parser exists.

Usage:
    python3 analysis/p0_probe.py --archive <path-to>/raw_collected_v3_15w
    python3 analysis/p0_probe.py --archive <path> --year 2018
    python3 analysis/p0_probe.py --archive <path> --limit 200   # per year
"""
from __future__ import annotations

import argparse
import csv
import gzip
import html
import json
import pathlib
import re
import sys
from collections import Counter

THETA = "9999.9"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
TABLE_RE = re.compile(r"<table.*?</table>", re.S | re.I)
TR_RE = re.compile(r"<tr.*?</tr>", re.S | re.I)
TD_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S | re.I)
CANCEL_ROW_RE = re.compile(r"취소마공지(.{0,400}?)</tr>", re.S)
NUM_RE = re.compile(r"^\d+(?:\.\d+)?$")
DASHES_RE = re.compile(r">\s*-{3,}\s*<")


def text(fragment: str) -> str:
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def table_rows(page: str) -> list[list[str]]:
    """First table of a page, as a list of rows of cell text."""
    m = TABLE_RE.search(page)
    if not m:
        return []
    return [[text(c) for c in TD_RE.findall(tr)] for tr in TR_RE.findall(m.group(0))]


def grid(rows: list[list[str]]) -> dict[int, list[str]]:
    """Map horse number -> that row's cells, indexed so cells[j] is column j.

    A data row starts with the horse number and is followed by one cell per
    column, the diagonal carrying the horse number again. Header, total and
    notice rows are shorter or do not start with a number, so they drop out.
    """
    out: dict[int, list[str]] = {}
    for r in rows:
        if len(r) >= 4 and r[0].isdigit():
            out[int(r[0])] = r
    return out


def cell(g: dict[int, list[str]], row: int, col: int) -> str | None:
    r = g.get(row)
    if r is None or col >= len(r):
        return None
    return r[col]


def iter_races(archive: pathlib.Path, year: str | None, limit: int | None):
    years = sorted(p for p in archive.glob("kra_*") if p.is_dir())
    if year:
        years = [p for p in years if year in p.name]
    for ydir in years:
        files = sorted(ydir.rglob("*.json.gz"))
        if limit:
            step = max(1, len(files) // limit)
            files = files[::step][:limit]
        print(f"  {ydir.name}: {len(files)} races", file=sys.stderr)
        for f in files:
            try:
                yield ydir.name, json.loads(gzip.decompress(f.read_bytes()))
            except Exception as exc:  # noqa: BLE001 - report, do not mask
                print(f"    unreadable {f.name}: {exc}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True, type=pathlib.Path)
    ap.add_argument("--year")
    ap.add_argument("--limit", type=int, help="sample this many races per year")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("outputs/p0"))
    args = ap.parse_args()

    if not args.archive.is_dir():
        sys.exit(f"no such archive: {args.archive}")
    args.out.mkdir(parents=True, exist_ok=True)

    c: Counter[str] = Counter()
    theta_rows: list[dict] = []
    token_rows: list[dict] = []

    print("scanning", file=sys.stderr)
    for _year, d in iter_races(args.archive, args.year, args.limit):
        rid = d.get("race_id", "?")
        pages = d.get("pages", {})
        c["races"] += 1

        both_rows = table_rows(pages["Both"]) if isinstance(pages.get("Both"), str) else []
        bc_rows = table_rows(pages["Bc"]) if isinstance(pages.get("Bc"), str) else []
        both, bc = grid(both_rows), grid(bc_rows)

        # --- probe 1: theta, against the quinella-place payout ------------
        for row, cells in both.items():
            for col, v in enumerate(cells):
                if col == 0 or v != THETA:
                    continue
                c["theta cells"] += 1
                lo, hi = min(row, col), max(row, col)
                partner = cell(both, col, row)          # the reverse ordering
                qp = cell(bc, lo, hi)
                if qp is None:
                    verdict = "unreadable"
                elif NUM_RE.match(qp):
                    verdict = "bet placed"              # supports display cap
                elif qp.startswith("----"):
                    verdict = "scratched"               # counter-example
                else:
                    verdict = "empty"                   # counter-example
                c[f"theta: {verdict}"] += 1
                theta_rows.append({
                    "race_id": rid, "row": row, "col": col,
                    "exacta": v, "exacta_reverse": partner,
                    "quinella_place": qp, "verdict": verdict,
                })

        # theta must not appear where the spec says it does not
        for pk in ("Scm", "Bc"):
            p = pages.get(pk)
            if isinstance(p, str) and THETA in p:
                c[f"theta in {pk} (unexpected)"] += 1

        # --- probe 2: '----' against the cancellation notice ---------------
        scm = pages.get("Scm")
        if isinstance(scm, str):
            m = CANCEL_ROW_RE.search(scm)
            if not m:
                c["cancel: notice row absent"] += 1
            else:
                notice = text(m.group(1))
                declared = "없습니다" not in notice
                tbl = TABLE_RE.search(scm)
                n_dashes = len(DASHES_RE.findall(tbl.group(0))) if tbl else 0
                key = ("declared" if declared else "none") + \
                      " & dashes" + (">0" if n_dashes else "=0")
                c[f"cancel: {key}"] += 1

        # --- probe 4: free-text odds tokens --------------------------------
        for pk, page in pages.items():
            variants = [page] if isinstance(page, str) else \
                       list(page.values()) if isinstance(page, dict) else []
            for h in variants:
                if not isinstance(h, str):
                    continue
                tbl = TABLE_RE.search(h)
                if not tbl:
                    continue
                for raw in TD_RE.findall(tbl.group(0)):
                    v = text(raw)
                    if not v or NUM_RE.match(v) or set(v) <= {"-"}:
                        continue
                    if v.isdigit() or len(v) > 30:
                        continue
                    if "공지" in v or "없습니다" in v or "매출" in v:
                        continue
                    c["odd tokens"] += 1
                    token_rows.append({"race_id": rid, "page_key": pk, "token": v})

    # ---------------------------------------------------------------- output
    tp = args.out / "theta_probe.csv"
    with tp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "race_id", "row", "col", "exacta", "exacta_reverse",
            "quinella_place", "verdict"])
        w.writeheader()
        w.writerows(theta_rows)

    tk = args.out / "odd_tokens.csv"
    with tk.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["race_id", "page_key", "token"])
        w.writeheader()
        w.writerows(token_rows)

    print()
    for k in sorted(c):
        print(f"  {k}: {c[k]}")

    support = c["theta: bet placed"]
    against = c["theta: scratched"] + c["theta: empty"]
    unread = c["theta: unreadable"]
    print()
    print("theta verdict")
    print(f"  supports display cap : {support}")
    print(f"  counter-examples     : {against}")
    print(f"  unreadable           : {unread}")
    if against or unread:
        print("  NOT CLEAN - inspect theta_probe.csv before writing this up")
    elif support:
        print("  clean: every theta pair carries a quinella-place payout")

    if token_rows:
        print()
        print("odd token frequencies")
        for tok, n in Counter(r["token"] for r in token_rows).most_common(20):
            print(f"  {n:6d}  {tok!r}")

    print()
    print(f"wrote {tp}")
    print(f"wrote {tk}")


if __name__ == "__main__":
    main()
