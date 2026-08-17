#!/usr/bin/env python3
"""Check KRA OpenAPI consistency against archived race identifiers.

This script is intentionally conservative with API calls.  It reads the race
overview API one year at a time and checks whether race IDs known from the
archive are present in the official API.

Typical use:

    DATA_GO_KR_SERVICE_KEY=... python3 scripts/check_api_consistency.py \
      --year 2025 \
      --sample-race-id 2025-01-24_3_08 \
      --sample-race-id 2025-01-26_3_04

The archive-side input can be either explicit --sample-race-id values or a text
file with one race_id per line.  A race_id has the form YYYY-MM-DD_meet_rcNo,
e.g. 2025-01-24_3_08.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable

API_BASE = "http://apis.data.go.kr/B551015/API3_1/raceInfo_1"

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
            date, meet, rc_no = value.strip().replace(".json.gz", "").split("_")
            year, month, day = date.split("-")
            if len(year) != 4 or len(month) != 2 or len(day) != 2:
                raise ValueError
            return cls(date=f"{year}-{month}-{day}", meet=int(meet), rc_no=int(rc_no))
        except Exception as exc:  # noqa: BLE001 - report the input value clearly
            raise argparse.ArgumentTypeError(f"invalid race_id {value!r}") from exc

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


def load_archive_race_ids(values: Iterable[str], files: Iterable[str]) -> set[RaceId]:
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
    return out


def api_item_to_race_id(item: dict) -> RaceId:
    rc_date = str(item["rcDate"])
    date = f"{rc_date[:4]}-{rc_date[4:6]}-{rc_date[6:8]}"
    return RaceId(date=date, meet=parse_meet(item["meet"]), rc_no=int(item["rcNo"]))


def fetch_year_overview(year: int, *, page_size: int, timeout: float, retries: int) -> list[dict]:
    page_no = 1
    all_items: list[dict] = []
    total_count: int | None = None
    while True:
        body, items = call_json(
            {
                "pageNo": str(page_no),
                "numOfRows": str(page_size),
                "rc_year": str(year),
            },
            timeout=timeout,
            retries=retries,
        )
        if total_count is None:
            total_count = int(body.get("totalCount", 0) or 0)
            print(f"api_year={year} totalCount={total_count} page_size={page_size}")
        all_items.extend(x for x in items if isinstance(x, dict))
        print(f"year={year} fetched_page={page_no} page_items={len(items)} cumulative={len(all_items)}")
        if len(all_items) >= total_count:
            break
        if not items:
            raise RuntimeError("pagination stopped with empty page before totalCount was reached")
        page_no += 1
    return all_items


def check_year(year: int, archive_ids_all: set[RaceId], *, page_size: int, timeout: float, retries: int) -> int:
    archive_ids = {rid for rid in archive_ids_all if int(rid.date[:4]) == year}
    print(f"\n=== year {year} ===")
    print(f"archive_sample_count={len(archive_ids)}")

    api_items = fetch_year_overview(year, page_size=page_size, timeout=timeout, retries=retries)
    api_ids = {api_item_to_race_id(item) for item in api_items}
    print(f"api_unique_race_count={len(api_ids)}")

    by_meet: dict[int, int] = {}
    for rid in api_ids:
        by_meet[rid.meet] = by_meet.get(rid.meet, 0) + 1
    print("api_count_by_meet=" + json.dumps(dict(sorted(by_meet.items())), ensure_ascii=False))

    missing = sorted(archive_ids - api_ids)
    present = sorted(archive_ids & api_ids)
    print(f"sample_present_count={len(present)}")
    for rid in present:
        print(f"present {rid}")
    if missing:
        print(f"sample_missing_count={len(missing)}")
        for rid in missing:
            print(f"MISSING {rid}")
        return 1

    print(f"year={year} status=ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, action="append", required=True)
    parser.add_argument("--sample-race-id", action="append", default=[])
    parser.add_argument("--race-id-file", action="append", default=[])
    parser.add_argument("--page-size", type=int, default=10000)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    archive_ids = load_archive_race_ids(args.sample_race_id, args.race_id_file)
    failures = 0
    for year in sorted(set(args.year)):
        failures += check_year(
            year,
            archive_ids,
            page_size=args.page_size,
            timeout=args.timeout,
            retries=args.retries,
        )

    if failures:
        print(f"overall_status=failed failed_years={failures}")
        return 1

    print("overall_status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
