#!/usr/bin/env python3
"""Build a race-id manifest from Dropbox raw KRA archive files.

This script enumerates Dropbox files under the raw archive root and writes a CSV
manifest keyed by race_id.  It is designed for exact API/archive consistency
checks without relying on the interactive Dropbox connector.

Required environment variable:

    DROPBOX_ACCESS_TOKEN

Example:

    DROPBOX_ACCESS_TOKEN=... python3 scripts/build_dropbox_archive_manifest.py \
      --dropbox-root /kra-analysis/data/raw_collected_v3_15w \
      --out data/external/dropbox_archive_race_ids.csv

The output CSV has columns:

    race_id,date,meet,rc_no,year,path,size,client_modified,server_modified
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DROPBOX_LIST_FOLDER_URL = "https://api.dropboxapi.com/2/files/list_folder"
DROPBOX_LIST_FOLDER_CONTINUE_URL = "https://api.dropboxapi.com/2/files/list_folder/continue"
RACE_FILE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<meet>\d+)_(?P<rc_no>\d+)\.json\.gz$")


@dataclass(frozen=True, order=True)
class RaceFile:
    race_id: str
    date: str
    meet: int
    rc_no: int
    year: int
    path: str
    size: int | None
    client_modified: str
    server_modified: str


def parse_race_file(entry: dict[str, Any]) -> RaceFile | None:
    if entry.get(".tag") != "file":
        return None
    name = str(entry.get("name", ""))
    match = RACE_FILE_RE.fullmatch(name)
    if not match:
        return None
    date = match.group("date")
    meet = int(match.group("meet"))
    rc_no = int(match.group("rc_no"))
    race_id = f"{date}_{meet}_{rc_no:02d}"
    return RaceFile(
        race_id=race_id,
        date=date,
        meet=meet,
        rc_no=rc_no,
        year=int(date[:4]),
        path=str(entry.get("path_display") or entry.get("path_lower") or ""),
        size=entry.get("size"),
        client_modified=str(entry.get("client_modified") or ""),
        server_modified=str(entry.get("server_modified") or ""),
    )


def dropbox_post(url: str, payload: dict[str, Any], *, token: str, timeout: float, retries: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "kra-v3-dropbox-manifest/1.0",
    }
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8")
            return json.loads(text)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_exc = RuntimeError(f"Dropbox HTTP {exc.code}: {detail}")
        except Exception as exc:  # noqa: BLE001 - retry network / transient failures
            last_exc = exc
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Dropbox request failed after {retries + 1} attempts: {last_exc}")


def iter_dropbox_entries(root: str, *, token: str, timeout: float, retries: int):
    payload = {
        "path": root,
        "recursive": True,
        "include_deleted": False,
        "include_has_explicit_shared_members": False,
        "include_mounted_folders": True,
        "limit": 2000,
    }
    data = dropbox_post(DROPBOX_LIST_FOLDER_URL, payload, token=token, timeout=timeout, retries=retries)
    page_no = 1
    while True:
        entries = data.get("entries", [])
        print(f"dropbox_page={page_no} entries={len(entries)} has_more={data.get('has_more')}", file=sys.stderr)
        for entry in entries:
            yield entry
        if not data.get("has_more"):
            break
        cursor = data.get("cursor")
        if not cursor:
            raise RuntimeError("Dropbox returned has_more=true without cursor")
        data = dropbox_post(
            DROPBOX_LIST_FOLDER_CONTINUE_URL,
            {"cursor": cursor},
            token=token,
            timeout=timeout,
            retries=retries,
        )
        page_no += 1


def write_manifest(path: str, rows: list[RaceFile]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["race_id", "date", "meet", "rc_no", "year", "path", "size", "client_modified", "server_modified"])
        for row in sorted(rows):
            writer.writerow([
                row.race_id,
                row.date,
                row.meet,
                row.rc_no,
                row.year,
                row.path,
                row.size if row.size is not None else "",
                row.client_modified,
                row.server_modified,
            ])
    print(f"wrote_manifest={out_path} rows={len(rows)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dropbox-root", default="/kra-analysis/data/raw_collected_v3_15w")
    parser.add_argument("--out", required=True)
    parser.add_argument("--year", type=int, action="append", default=[])
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    token = os.environ.get("DROPBOX_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("DROPBOX_ACCESS_TOKEN is missing or empty")

    wanted_years = set(args.year)
    rows: list[RaceFile] = []
    seen: set[str] = set()
    duplicate_count = 0
    for entry in iter_dropbox_entries(args.dropbox_root, token=token, timeout=args.timeout, retries=args.retries):
        race_file = parse_race_file(entry)
        if race_file is None:
            continue
        if wanted_years and race_file.year not in wanted_years:
            continue
        if race_file.race_id in seen:
            duplicate_count += 1
            print(f"WARN duplicate_race_id={race_file.race_id} path={race_file.path}", file=sys.stderr)
        seen.add(race_file.race_id)
        rows.append(race_file)

    by_year: dict[int, int] = {}
    by_meet: dict[tuple[int, int], int] = {}
    for row in rows:
        by_year[row.year] = by_year.get(row.year, 0) + 1
        key = (row.year, row.meet)
        by_meet[key] = by_meet.get(key, 0) + 1

    print("archive_count_by_year=" + json.dumps(dict(sorted(by_year.items())), ensure_ascii=False))
    print(
        "archive_count_by_year_meet="
        + json.dumps({f"{year}_{meet}": count for (year, meet), count in sorted(by_meet.items())}, ensure_ascii=False)
    )
    print(f"archive_duplicate_race_id_count={duplicate_count}")

    write_manifest(args.out, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
