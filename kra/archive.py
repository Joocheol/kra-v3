"""Walking the archive and writing the parsed result.

Layout on disk:

    raw_collected_v3_15w/kra_YYYY/raw_archive/YYYY/YYYY-MM/YYYY-MM-DD_{meet}_{no}.json.gz

The month directory is the unit of work. Parsing is CPU-bound (one HTML parse
per page, 3+2N pages per race), so months are farmed out to worker processes.
Output partitions are keyed by month too, which means **no two workers ever
open the same file** -- the parallelism needs no locking and no merge step.

The archive is read-only. Nothing here opens it for writing.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import pathlib
from dataclasses import dataclass

from .race import CellRow, parse_race

__all__ = ["Month", "months", "parse_month", "write_manifest"]


@dataclass(frozen=True)
class Month:
    key: str                      # "2018-05"
    year: int
    files: tuple[pathlib.Path, ...]


def months(archive: pathlib.Path, year: int | None = None,
           limit: int | None = None) -> list[Month]:
    """Month-sized work units, sorted so a run is reproducible."""
    buckets: dict[str, list[pathlib.Path]] = {}
    for ydir in sorted(archive.glob("kra_*")):
        if year is not None and str(year) not in ydir.name:
            continue
        for f in ydir.rglob("*.json.gz"):
            buckets.setdefault(f.parent.name, []).append(f)
    out = []
    for key in sorted(buckets):
        files = sorted(buckets[key])
        if limit:
            files = files[:limit]
        out.append(Month(key=key, year=int(key[:4]), files=tuple(files)))
    return out


def _cells_path(out: pathlib.Path, page_key: str, month: str) -> pathlib.Path:
    # 3Bc / 3Both start with a digit; keep the directory name explicit rather
    # than sanitising it, so the partition maps back to the page key exactly.
    return out / "cells" / f"page_key={page_key}" / f"{month}.csv.gz"


def parse_month(month: Month, out_dir: pathlib.Path, want_cells: bool,
                sections: tuple[str, ...]) -> dict:
    """Parse one month. Returns race summaries plus counts for the manifest.

    Runs in a worker process, so it returns only small data: the per-race
    summaries (a few hundred bytes each) and file statistics. The cell rows --
    millions of them -- are written straight to disk here and never crossed
    back over the process boundary.
    """
    summaries: list[dict] = []
    problems: list[dict] = []
    writers: dict[str, tuple[io.TextIOWrapper, csv.DictWriter]] = {}
    counts: dict[str, int] = {}

    try:
        for path in month.files:
            try:
                payload = json.loads(gzip.decompress(path.read_bytes()))
            except Exception as exc:                      # noqa: BLE001
                problems.append({"file": path.name, "error": f"unreadable: {exc}"})
                continue
            try:
                race, rows = parse_race(payload, sections=sections)
            except Exception as exc:                      # noqa: BLE001
                problems.append({"file": path.name, "error": f"parse: {exc}"})
                continue

            summaries.append(race.summary())
            if race.problems:
                problems.append({"race_id": race.race_id, "problems": race.problems})
            if not want_cells:
                continue

            for row in rows:
                pk = row.page_key
                if pk not in writers:
                    p = _cells_path(out_dir, pk, month.key)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    fh = gzip.open(p, "wt", newline="", encoding="utf-8")
                    w = csv.DictWriter(fh, fieldnames=list(CellRow.FIELDS))
                    w.writeheader()
                    writers[pk] = (fh, w)
                    counts[pk] = 0
                writers[pk][1].writerow(row.as_dict())
                counts[pk] += 1
    finally:
        for fh, _ in writers.values():
            fh.close()

    files = []
    for pk in sorted(counts):
        p = _cells_path(out_dir, pk, month.key)
        files.append({
            "path": str(p.relative_to(out_dir)),
            "page_key": pk, "month": month.key, "rows": counts[pk],
            "bytes": p.stat().st_size, "sha256": _sha256(p),
        })
    return {"month": month.key, "n_races": len(summaries),
            "summaries": summaries, "problems": problems, "files": files}


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(out_dir: pathlib.Path, payload: dict) -> pathlib.Path:
    """Per-partition row counts, sizes and hashes.

    Without this a rebuild cannot be checked when the raw archive is not at
    hand, and a partial run is indistinguishable from a complete one.
    """
    p = out_dir / "manifest.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p
