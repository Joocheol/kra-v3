#!/usr/bin/env python3
"""Check KRA OpenAPI consistency against archived race identifiers.

This script is conservative with API calls.  It reads the race overview API by
year and meet, because the provider defaults to Seoul when ``meet`` is omitted.
For the archived years currently in scope this means at most 3 calls per year,
before pagination.

It can do two kinds of checks:

1. API-only smoke check, optionally with --sample-race-id values.
2. Full bidirectional diff if --archive-root or --race-id-file is supplied.

A race_id has the form YYYY-MM-DD_meet_rcNo, e.g. 2025-01-24_3_08.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

API_BASE = "http://apis.data.go.kr/B551015/API3_1/raceInfo_1"
MEET_CODES = (1, 2, 3)
RACE_FILE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<meet>\d+)_(?P<rc_no>\d+)\.json\.gz$")

MEET_NAME_TO_CODE = {
    "서울": 1,
    "서울경마": 1,
    "SEOUL": 1,
    "제주": 2,
    "제주경마": 2,
    "JEJU": 2,
    "부산경남": 3,
    "부경": 3,
    "부산": 3,
    "부산경남경마": 3,
    "BUSAN": 3,
}


@dataclass(frozen=True, order=True)
class RaceId:
    date: str
    meet: int
    rc_no: int

    @classmethod
    def parse(cls, value: str) -> "RaceId":
        try:
            base = Path(value.strip()).name
            base = base.replace(".json.gz", "")
            date, meet, rc_no = base.split("_")
            year, month, day = date.split("-")
            if len(year) != 4 or len(month) != 2 or len(day) != 2:
                raise ValueError
            return cls(date=f"{year}-{month}-{day}", meet=int(meet), rc_no=int(rc_no))
        except Exception as exc:  # noqa: BLE001 - report the input value clearly
            raise argparse.ArgumentTypeError(f"invalid race_id {value!r}") from exc

    @property
    def year(self) -> int:
        return int(self.date[:4])

    @property
    def api_date(self) -> str:
        return self.date.replace("-", "")

    def __str__(self) -> str:
        return f"{self.date}_{self.meet}_{self.rc_no:02d}"


def parse_meet(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    if text in MEET_NAME_TO_CODE:
        return MEET_NAME_TO_CODE[text]
    raise ValueError(f"unknown meet value: {value!r}")


def normalize_items(items):
    if items in (None, ""):
        return []
    if isinstance(items, dict) and "item" in items:
        items = items["item"]
    if isinstance(items, list):
        return items
    return [items]


def get_nested(obj, *path):
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def call_json(params: dict[str, str], *, timeout: float, retries: int) -> tuple[dict, list[dict]]:
    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
    if not key:
        raise RuntimeError("DATA_GO_KR_SERVICE_KEY is missing or empty")
    query = dict(params)
    query["serviceKey"] = key
    query["_type"] = "json"
    url = API_BASE + "?" + urllib.parse.urlencode(query, safe="%")
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kra-v3-api-consistency/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read(2_000_000).decode("utf-8", errors="replace")
            data = json.loads(text)
            header = get_nested(data, "response", "header") or {}
            body = get_nested(data, "response", "body") or {}
            result_code = str(header.get("resultCode"))
            result_msg = header.get("resultMsg")
            if result_code not in {"00", "0", "None"}:
                raise RuntimeError(f"API resultCode={result_code} resultMsg={result_msg}")
            return body, normalize_items(get_nested(body, "items"))
        except Exception as exc:  # noqa: BLE001 - retry transient API/network failures
            last_exc = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"API request failed after {retries + 1} attempts: {last_exc}")


def load_archive_race_ids(values: Iterable[str], files: Iterable[str], roots: Iterable[str]) -> set[RaceId]:
    out: set[RaceId] = set()
    for value in values:
        if value.strip():
            out.add(RaceId.parse(value))
    for path in files:
        with open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.add(RaceId.parse(line))
    for root in roots:
        root_path = Path(root).expanduser()
        if not root_path.exists():
            raise FileNotFoundError(f"archive root not found: {root_path}")
        count = 0
        for file_path in root_path.rglob("*.json.gz"):
            if RACE_FILE_RE.search(file_path.name):
                out.add(RaceId.parse(file_path.name))
                count += 1
        print(f"archive_root={root_path} race_file_count={count}")
    return out


def api_item_to_race_id(item: dict) -> RaceId:
    rc_date = str(item["rcDate"])
    date = f"{rc_date[:4]}-{rc_date[4:6]}-{rc_date[6:8]}"
    return RaceId(date=date, meet=parse_meet(item["meet"]), rc_no=int(item["rcNo"]))


def fetch_year_meet_overview(
    year: int,
    meet: int,
    *,
    page_size: int,
    timeout: float,
    retries: int,
) -> list[dict]:
    page_no = 1
    all_items: list[dict] = []
    total_count: int | None = None
    while True:
        body, items = call_json(
            {
                "pageNo": str(page_no),
                "numOfRows": str(page_size),
                "rc_year": str(year),
                "meet": str(meet),
            },
            timeout=timeout,
            retries=retries,
        )
        if total_count is None:
            total_count = int(body.get("totalCount", 0) or 0)
            print(f"api_year={year} meet={meet} totalCount={total_count} page_size={page_size}")
        all_items.extend(x for x in items if isinstance(x, dict))
        print(
            f"year={year} meet={meet} fetched_page={page_no} "
            f"page_items={len(items)} cumulative={len(all_items)}"
        )
        if len(all_items) >= total_count:
            break
        if not items:
            raise RuntimeError("pagination stopped with empty page before totalCount was reached")
        page_no += 1
    return all_items


def fetch_year_overview(year: int, *, page_size: int, timeout: float, retries: int) -> list[dict]:
    all_items: list[dict] = []
    for meet in MEET_CODES:
        all_items.extend(
            fetch_year_meet_overview(
                year,
                meet,
                page_size=page_size,
                timeout=timeout,
                retries=retries,
            )
        )
    return all_items


def write_diff_csv(path: str | None, rows: Iterable[RaceId], side: str) -> None:
    if not path:
        return
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["side", "race_id", "date", "meet", "rc_no"])
        for rid in rows:
            writer.writerow([side, str(rid), rid.date, rid.meet, rid.rc_no])
    print(f"wrote {side} csv={out_path}")


def check_year(year: int, archive_ids_all: set[RaceId], *, page_size: int, timeout: float, retries: int, diff_dir: str | None, fail_on_diff: bool) -> int:
    archive_ids = {rid for rid in archive_ids_all if rid.year == year}
    print(f"\n=== year {year} ===")
    print(f"archive_race_count={len(archive_ids)}")

    api_items = fetch_year_overview(year, page_size=page_size, timeout=timeout, retries=retries)
    api_ids = {api_item_to_race_id(item) for item in api_items}
    print(f"api_raw_row_count={len(api_items)}")
    print(f"api_unique_race_count={len(api_ids)}")
    if len(api_items) != len(api_ids):
        print(f"WARN duplicate_api_rows={len(api_items) - len(api_ids)}")

    by_meet: dict[int, int] = {}
    for rid in api_ids:
        by_meet[rid.meet] = by_meet.get(rid.meet, 0) + 1
    print("api_count_by_meet=" + json.dumps(dict(sorted(by_meet.items())), ensure_ascii=False))

    api_only = sorted(api_ids - archive_ids) if archive_ids else []
    archive_only = sorted(archive_ids - api_ids) if archive_ids else []
    matched = sorted(archive_ids & api_ids) if archive_ids else []

    print(f"matched_count={len(matched)}")
    print(f"api_only_count={len(api_only)}")
    print(f"archive_only_count={len(archive_only)}")

    for rid in api_only[:20]:
        print(f"API_ONLY {rid}")
    if len(api_only) > 20:
        print(f"API_ONLY ... {len(api_only) - 20} more")
    for rid in archive_only[:20]:
        print(f"ARCHIVE_ONLY {rid}")
    if len(archive_only) > 20:
        print(f"ARCHIVE_ONLY ... {len(archive_only) - 20} more")

    if diff_dir:
        write_diff_csv(str(Path(diff_dir) / f"api_only_{year}.csv"), api_only, "api_only")
        write_diff_csv(str(Path(diff_dir) / f"archive_only_{year}.csv"), archive_only, "archive_only")

    if (api_only or archive_only) and fail_on_diff:
        print(f"year={year} status=diff")
        return 1

    print(f"year={year} status=ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, action="append", required=True)
    parser.add_argument("--sample-race-id", action="append", default=[])
    parser.add_argument("--race-id-file", action="append", default=[])
    parser.add_argument("--archive-root", action="append", default=[])
    parser.add_argument("--diff-dir", default=None)
    parser.add_argument("--fail-on-diff", action="store_true")
    parser.add_argument("--page-size", type=int, default=10000)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    archive_ids = load_archive_race_ids(args.sample_race_id, args.race_id_file, args.archive_root)
    failures = 0
    for year in sorted(set(args.year)):
        failures += check_year(
            year,
            archive_ids,
            page_size=args.page_size,
            timeout=args.timeout,
            retries=args.retries,
            diff_dir=args.diff_dir,
            fail_on_diff=args.fail_on_diff,
        )

    if failures:
        print(f"overall_status=failed failed_years={failures}")
        return 1

    print("overall_status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
