#!/usr/bin/env python3
"""Parse the KRA dividend archive into tables.

    python3 parse_archive.py --archive ~/Dropbox/.../raw_collected_v3_15w \
                             --out outputs/parsed

Produces

    outputs/parsed/races.jsonl.gz              one line per race
    outputs/parsed/cells/page_key=…/YYYY-MM.csv.gz   one row per cell
    outputs/parsed/manifest.json               counts, sizes, sha256
    outputs/parsed/problems.jsonl              anything that did not parse

Race-level output is cheap and always written. Cell-level output is the bulk
of the work (tens of millions of rows) and is opt-in with --cells.

Standard library only, on purpose: the machine running this has no lxml, no
pandas, and the input is EUC-KR HTML already decoded into JSON strings by the
collector.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import pathlib
import sys
import time

from kra.archive import months, parse_month, write_manifest


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True, type=pathlib.Path,
                    help="raw_collected_v3_15w (read-only)")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("outputs/parsed"))
    ap.add_argument("--cells", action="store_true",
                    help="also write one row per cell (large)")
    ap.add_argument("--sections", default="body,foot",
                    help="table sections to emit as cells (default body,foot)")
    ap.add_argument("--year", type=int, help="restrict to one year")
    ap.add_argument("--limit", type=int, metavar="N",
                    help="at most N races per month, for a quick trial run")
    ap.add_argument("--workers", type=int, default=0,
                    help="worker processes (default: cpu_count-1)")
    args = ap.parse_args()

    if not args.archive.is_dir():
        sys.exit(f"no such archive: {args.archive}")
    sections = tuple(s.strip() for s in args.sections.split(",") if s.strip())
    bad = set(sections) - {"head", "body", "foot"}
    if bad:
        sys.exit(f"unknown section(s): {sorted(bad)}")

    work = months(args.archive, year=args.year, limit=args.limit)
    if not work:
        sys.exit("nothing to parse")
    total = sum(len(m.files) for m in work)
    workers = args.workers or max(1, (__import__("os").cpu_count() or 2) - 1)
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"{total:,} races in {len(work)} months, {workers} workers", file=sys.stderr)
    if args.cells:
        print(f"cells: on (sections={','.join(sections)})", file=sys.stderr)

    started = time.time()
    races_path = args.out / "races.jsonl.gz"
    problems_path = args.out / "problems.jsonl"
    files, n_races, n_problems = [], 0, 0
    done = 0

    with gzip.open(races_path, "wt", encoding="utf-8") as rfh, \
            problems_path.open("w", encoding="utf-8") as pfh, \
            cf.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(parse_month, m, args.out, args.cells, sections): m
                   for m in work}
        for fut in cf.as_completed(futures):
            m = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:                       # noqa: BLE001
                print(f"  {m.key}: FAILED {exc}", file=sys.stderr)
                n_problems += 1
                pfh.write(json.dumps({"month": m.key, "error": str(exc)},
                                     ensure_ascii=False) + "\n")
                continue
            for s in res["summaries"]:
                rfh.write(json.dumps(s, ensure_ascii=False) + "\n")
            for p in res["problems"]:
                pfh.write(json.dumps(p, ensure_ascii=False) + "\n")
            files += res["files"]
            n_races += res["n_races"]
            n_problems += len(res["problems"])
            done += 1
            print(f"  [{done}/{len(work)}] {res['month']}: {res['n_races']} races",
                  file=sys.stderr)

    elapsed = time.time() - started
    n_cells = sum(f["rows"] for f in files)
    n_bytes = sum(f["bytes"] for f in files)
    write_manifest(args.out, {
        "archive": str(args.archive), "sections": list(sections),
        "cells_written": args.cells, "n_races": n_races, "n_cells": n_cells,
        "elapsed_seconds": round(elapsed, 1),
        "files": sorted(files, key=lambda f: f["path"]),
    })

    print(f"\n  races   {n_races:,}   -> {races_path}")
    if args.cells:
        print(f"  cells   {n_cells:,}   {human(n_bytes)} in {len(files)} partitions")
    print(f"  문제    {n_problems:,}   -> {problems_path}")
    print(f"  걸린 시간 {elapsed / 60:.1f}분")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
