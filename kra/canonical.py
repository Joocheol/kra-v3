"""Bridge the versioned ``kra-data`` release to the legacy grid interface.

The research code predates the normalized OpenAPI release and consumes one
race file plus five families of CSV grid partitions.  This module verifies the
official v1.0 bundle and materializes that interface without modifying the
frozen, HTML-derived ``데이터`` directory.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable


DROPBOX_SOURCE = "/앱/kra-data/research/2016-2025/"
PROTOCOL_YEARS = (2016, 2017, 2018, 2019, 2022, 2023, 2024, 2025)
REQUIRED_FILES = (
    "races.jsonl.gz",
    "entries.jsonl.gz",
    "results.jsonl.gz",
    "sales.jsonl.gz",
    "odds.jsonl.gz",
    "coverage.jsonl.gz",
    "manifest.json",
    "SHA256SUMS",
)
V1_SHA256 = {
    "races.jsonl.gz": "78ad37bfab5518004db7a88f1dcbfa6ca76d87acf52dd4c4d90af2e8bd9378a1",
    "entries.jsonl.gz": "7eb7933261ba316c7bdb3ecc503b1b1276cb8e43bd7983963baef9900fb27502",
    "results.jsonl.gz": "0599f42f36d9f942461bdcfdb592e419faf5067ea624f2e3baf02e35f5535ce1",
    "sales.jsonl.gz": "3652e97e35d579820b55aa6b58d5a6f190962ad6ab2e76cead1a081a708400b1",
    "odds.jsonl.gz": "c0dee9784c1479f5bf73aee1b2211bcb3e4c06dde07cf4d6bd2d65d5980a0d22",
    "coverage.jsonl.gz": "a7521773b27d6458a455f1bd2ce0668f9be7950ceca111d34683475f5c491bcf",
    "manifest.json": "8ae32df8175afca66462ff6dec428c04a82379d8028e5748a3352f084e5db169",
}
V1_TABLES = {
    "races": 24436,
    "race_record_rows": 261354,
    "entries_rows": 261354,
    "results_rows": 261354,
    "sales_rows": 163844,
    "odds_rows": 29196005,
    "coverage_rows": 24436,
}
POOL_LABEL = {
    "WIN": "단승식",
    "PLC": "연승식",
    "QNL": "복승식",
    "EXA": "쌍승식",
    "QPL": "복연승식",
    "TLA": "삼복승식",
    "TRI": "삼쌍승식",
}
POOL_COVERAGE = {
    "WIN": "win",
    "PLC": "plc",
    "QNL": "qnl",
    "EXA": "exa",
    "QPL": "qpl",
    "TLA": "tla",
    "TRI": "tri",
}
MEET_NAME = {1: "서울", 2: "제주", 3: "부산경남"}
WITHDRAWAL_LABELS = {"출전제외", "출전취소"}
CELL_FIELDS = (
    "race_id", "page_key", "page_variant", "section", "row", "col",
    "row_header", "col_group", "col_header", "cell_raw", "rowspan",
    "colspan", "spanned",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_v1_source(source: Path, *, official: bool = True) -> dict[str, Any]:
    """Validate files, declared checksums, and the normalized schema contract."""
    missing = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"canonical source is missing: {', '.join(missing)}")

    declared: dict[str, str] = {}
    for line in (source / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        declared[name.lstrip("*")] = digest
    if set(declared) != set(V1_SHA256):
        raise ValueError("SHA256SUMS does not list the seven canonical payload files")
    for name, expected in declared.items():
        actual = _sha256(source / name)
        if actual != expected:
            raise ValueError(f"checksum mismatch for {name}: {actual} != {expected}")
    if official and declared != V1_SHA256:
        raise ValueError("source checksums do not match the official kra-data v1.0 release")

    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2:
        raise ValueError(f"unsupported schema_version: {manifest.get('schema_version')!r}")
    if manifest.get("race_id_format") != "YYYYMMDD-meet-rcNo":
        raise ValueError("unexpected canonical race_id format")
    if official:
        tables = manifest.get("tables", {})
        for name, expected in V1_TABLES.items():
            if tables.get(name) != expected:
                raise ValueError(f"unexpected manifest count for {name}")
    return manifest


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def _legacy_id(race_id: str) -> tuple[str, str, int, int]:
    date_raw, meet_raw, race_raw = race_id.split("-")
    date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
    meet, race_no = int(meet_raw), int(race_raw)
    return f"{date}_{meet}_{race_no:02d}", date, meet, race_no


def _complete_races(source: Path, years: set[int]) -> set[str]:
    selected: set[str] = set()
    for row in _read_jsonl(source / "coverage.jsonl.gz"):
        if int(row["race_id"][:4]) not in years:
            continue
        complete = all(
            row.get(f"odds_{suffix}") and row.get(f"sales_{suffix}")
            for suffix in POOL_COVERAGE.values()
        )
        if complete:
            selected.add(row["race_id"])
    return selected


def _race_rows(source: Path, race_ids: set[str]) -> list[dict[str, Any]]:
    meta = {
        row["race_id"]: row
        for row in _read_jsonl(source / "races.jsonl.gz")
        if row["race_id"] in race_ids
    }
    horses: dict[str, set[int]] = defaultdict(set)
    names: dict[tuple[str, int], str] = {}
    for row in _read_jsonl(source / "entries.jsonl.gz"):
        race_id = row["race_id"]
        if race_id in race_ids:
            horse = int(row["chulNo"])
            horses[race_id].add(horse)
            names[(race_id, horse)] = str(row.get("hrName") or horse)

    scratched: dict[str, set[int]] = defaultdict(set)
    arrivals: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in _read_jsonl(source / "results.jsonl.gz"):
        race_id = row["race_id"]
        if race_id not in race_ids:
            continue
        horse = int(row["chulNo"])
        if str(row.get("differ") or "").strip() in WITHDRAWAL_LABELS:
            scratched[race_id].add(horse)
        order = str(row.get("stOrd") or "").strip()
        if order.isdigit() and int(order) > 0:
            arrivals[race_id].append((int(order), horse))

    sales: dict[str, dict[str, int]] = defaultdict(dict)
    for row in _read_jsonl(source / "sales.jsonl.gz"):
        race_id, pool = row["race_id"], row["pool_code"]
        if race_id not in race_ids:
            continue
        if pool in sales[race_id]:
            raise ValueError(f"duplicate sales key: {race_id} {pool}")
        sales[race_id][pool] = int(row["amt"])

    output = []
    for race_id in sorted(race_ids):
        if race_id not in meta:
            raise ValueError(f"coverage race is absent from races: {race_id}")
        registered = sorted(horses[race_id])
        withdrawn = sorted(scratched[race_id])
        active = set(registered) - set(withdrawn)
        arrival = [horse for _, horse in sorted(arrivals[race_id]) if horse in active]
        if not set(arrival).issubset(active):
            raise ValueError(f"result includes a non-active entry: {race_id}")
        if set(sales[race_id]) != set(POOL_LABEL):
            raise ValueError(f"incomplete sales pools: {race_id}")
        legacy_id, date, meet, race_no = _legacy_id(race_id)
        sales_out = {
            POOL_LABEL[pool]: f"{amount:,}원"
            for pool, amount in sales[race_id].items()
        }
        sales_out["총매출액"] = f"{sum(sales[race_id].values()):,}원"
        output.append({
            "race_id": legacy_id,
            "canonical_race_id": race_id,
            "date": date,
            "meet": meet,
            "meet_name": MEET_NAME.get(meet, str(meet)),
            "race_no": race_no,
            "n_registered": len(registered),
            "horses": registered,
            "arrival": arrival,
            "n_arrival": len(arrival),
            "scratched": withdrawn,
            "cancel_notice": (
                ", ".join(names[(race_id, horse)] for horse in withdrawn)
                if withdrawn else "취소마가 없습니다."
            ),
            "sales": sales_out,
            "pages": {
                "Scm": 1, "Both": 1, "Bc": 1,
                "3Bc": len(registered), "3Both": len(registered),
            },
            "problems": [],
        })
    return output


def _odds_text(value: Any) -> str:
    return format(Decimal(str(value)), ".1f")


def _pair(row: dict[str, Any]) -> tuple[int, int]:
    return int(row["chulNo1"]), int(row["chulNo2"])


def _triple(row: dict[str, Any]) -> tuple[int, int, int]:
    first = row.get("chulNo", row.get("chulNo1"))
    return int(first), int(row["chulNo2"]), int(row["chulNo3"])


def _cell(row: dict[str, Any]) -> tuple[str, dict[str, str]]:
    pool = row["pool_code"]
    base = {
        "page_variant": "", "section": "body", "row": "", "col": "",
        "row_header": "", "col_group": "", "col_header": "",
        "cell_raw": _odds_text(row["odds"]), "rowspan": "1",
        "colspan": "1", "spanned": "0",
    }
    if pool in {"WIN", "PLC"}:
        page = "Scm"
        base.update(row_header=str(int(row["chulNo"])), col_group=POOL_LABEL[pool])
    elif pool == "QNL":
        page = "Scm"
        first, second = sorted(_pair(row))
        base.update(row_header=str(first), col_header=str(second), col_group=POOL_LABEL[pool])
    elif pool == "EXA":
        page = "Both"
        first, second = _pair(row)
        base.update(row_header=str(second), col_header=str(first))
    elif pool == "QPL":
        page = "Bc"
        first, second = sorted(_pair(row))
        base.update(row_header=str(first), col_header=str(second))
    elif pool == "TLA":
        page = "3Bc"
        first, second, third = sorted(_triple(row))
        base.update(page_variant=str(first), col_header=str(second), row_header=str(third))
    elif pool == "TRI":
        page = "3Both"
        first, second, third = _triple(row)
        base.update(page_variant=str(first), col_header=str(second), row_header=str(third))
    else:
        raise ValueError(f"unknown pool_code: {pool!r}")
    base["page_key"] = page
    return page, base


@dataclass
class _OpenPartition:
    text: Any
    writer: csv.DictWriter


class _PartitionWriters:
    """Spool by page/year, then split and verify final month partitions."""

    def __init__(self, root: Path):
        self.root = root
        self.spool = root / ".cells-spool"
        self.month_spool = root / ".month-spool"
        self.opened: dict[Path, _OpenPartition] = {}
        self.expected_rows: dict[tuple[str, str], int] = defaultdict(int)

    @staticmethod
    def _close(item: _OpenPartition) -> None:
        item.text.close()

    def writerow(self, page: str, month: str, row: dict[str, str]) -> None:
        path = self.spool / f"page_key={page}" / f"{month[:4]}.csv"
        item = self.opened.get(path)
        if item is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = path.open("w", encoding="utf-8", newline="")
            writer = csv.DictWriter(
                text, fieldnames=("_month",) + CELL_FIELDS, lineterminator="\n"
            )
            writer.writeheader()
            item = _OpenPartition(text, writer)
            self.opened[path] = item
        item.writer.writerow({"_month": month, **row})
        self.expected_rows[(page, month)] += 1

    @staticmethod
    def _open_month(path: Path) -> _OpenPartition:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.open("w", encoding="utf-8", newline="")
        writer = csv.DictWriter(text, fieldnames=CELL_FIELDS, lineterminator="\n")
        writer.writeheader()
        return _OpenPartition(text, writer)

    def close(self) -> None:
        for item in self.opened.values():
            self._close(item)
        self.opened.clear()

        for annual in sorted(self.spool.glob("page_key=*/*.csv")):
            page = annual.parent.name.removeprefix("page_key=")
            months: dict[str, _OpenPartition] = {}
            with annual.open("r", encoding="utf-8", newline="") as source:
                for row in csv.DictReader(source):
                    month = row.pop("_month")
                    if month not in months:
                        months[month] = self._open_month(
                            self.month_spool / f"page_key={page}" / f"{month}.csv"
                        )
                    months[month].writer.writerow(row)
            for item in months.values():
                self._close(item)

        for plain in sorted(self.month_spool.glob("page_key=*/*.csv")):
            page = plain.parent.name.removeprefix("page_key=")
            month = plain.stem
            target = self.root / "cells" / plain.parent.name / f"{plain.name}.gz"
            target.parent.mkdir(parents=True, exist_ok=True)
            # Complete the gzip member in memory before the filesystem sees
            # it.  Monthly partitions bound memory use and a single write
            # avoids partially persisted streaming members on mounted drives.
            target.write_bytes(gzip.compress(plain.read_bytes(), mtime=0))
            observed = -1
            with gzip.open(target, "rt", encoding="utf-8", newline="") as check:
                observed = sum(1 for _ in check) - 1
            expected = self.expected_rows[(page, month)]
            if observed != expected:
                raise ValueError(
                    f"partition row count mismatch: {page} {month}: "
                    f"{observed} != {expected}"
                )
            with target.open("rb") as stable:
                os.fsync(stable.fileno())
        shutil.rmtree(self.spool)
        shutil.rmtree(self.month_spool)


def materialize_legacy_input(
    source: Path,
    output: Path,
    *,
    years: Iterable[int] = PROTOCOL_YEARS,
    official: bool = True,
) -> dict[str, Any]:
    """Create a separate legacy-compatible input tree from canonical v1.0."""
    source, output = source.resolve(), output.resolve()
    manifest = verify_v1_source(source, official=official)
    selected_years = set(years)
    if not selected_years:
        raise ValueError("at least one year is required")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")

    race_ids = _complete_races(source, selected_years)
    races = _race_rows(source, race_ids)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        with (temp / "races.jsonl.gz").open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                with io.TextIOWrapper(zipped, encoding="utf-8") as text:
                    for race in races:
                        text.write(json.dumps(race, ensure_ascii=False, sort_keys=True) + "\n")

        writers = _PartitionWriters(temp)
        odds_rows = 0
        try:
            for row in _read_jsonl(source / "odds.jsonl.gz"):
                race_id = row["race_id"]
                if race_id not in race_ids:
                    continue
                legacy_id, date, _, _ = _legacy_id(race_id)
                page, cell = _cell(row)
                cell["race_id"] = legacy_id
                writers.writerow(page, date[:7], cell)
                odds_rows += 1
        finally:
            writers.close()

        output_manifest = {
            "adapter_schema_version": 1,
            "source": {
                "dropbox_path": DROPBOX_SOURCE,
                "release": "kra-data v1.0",
                "schema_version": manifest["schema_version"],
                "sha256": V1_SHA256 if official else "verified from SHA256SUMS",
            },
            "selection": {
                "years": sorted(selected_years),
                "rule": "all seven odds and sales pools are present",
                "race_count": len(races),
                "odds_row_count": odds_rows,
            },
            "legacy_input": {
                "races": "races.jsonl.gz",
                "cells": "cells/page_key=<page>/<YYYY-MM>.csv.gz",
            },
        }
        (temp / "manifest.json").write_text(
            json.dumps(output_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for directory in sorted(
            (path for path in temp.rglob("*") if path.is_dir()), reverse=True
        ):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        descriptor = os.open(temp, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        temp.rename(output)
        descriptor = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return output_manifest
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
