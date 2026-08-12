#!/usr/bin/env python3
"""Recover actual payouts whose betting-grid display is capped at ``9999.9``.

The grid archive tells us which potential payout was capped.  Race outcomes
tell us which grid cells could have won.  For only those races, this script
reads KRA's detailed result page and intersects its actual paid dividends with
the capped grid cells.  One detail-page request recovers every affected pool
in that race.

    python3 collect_winning_payouts.py --data 데이터
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import pathlib
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from kra.results import (
    DISPLAY_CAP,
    WinningDividend,
    detail_url,
    parse_winning_dividends,
    ticket_candidates,
)

USER_AGENT = "kra-v3-research/1.0 (academic reproducibility; one page per race)"

POOL = {
    "단승식": {"key": "win", "page": "Scm", "take": Fraction(80, 100)},
    "연승식": {"key": "place", "page": "Scm", "take": Fraction(80, 100)},
    "복승식": {"key": "quinella", "page": "Scm", "take": Fraction(73, 100)},
    "쌍승식": {"key": "exacta", "page": "Both", "take": Fraction(73, 100)},
    "복연승식": {"key": "quinella_place", "page": "Bc", "take": Fraction(73, 100)},
    "삼복승식": {"key": "trio", "page": "3Bc", "take": Fraction(73, 100)},
    "삼쌍승식": {"key": "trifecta", "page": "3Both", "take": Fraction(73, 100)},
}
UNORDERED = {"복승식", "복연승식", "삼복승식"}
MULTI_PAYOUT = {"연승식", "복연승식"}


@dataclass(frozen=True, order=True)
class CappedCandidate:
    race_id: str
    pool: str
    combination: tuple[int, ...]


def load_races(path: pathlib.Path) -> dict[str, dict]:
    races = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            race = json.loads(line)
            races[race["race_id"]] = race
    return races


def _canonical(pool: str, combination: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted(combination)) if pool in UNORDERED else combination


def _grid_combination(row: dict[str, str]) -> tuple[str, tuple[int, ...]] | None:
    page = row["page_key"]
    rh, ch, variant = row["row_header"], row["col_header"], row["page_variant"]
    if not rh.isdigit():
        return None
    horse = int(rh)
    if page == "Scm":
        group = row["col_group"]
        if group in ("단승식", "연승식"):
            return group, (horse,)
        if group == "복승식" and ch.isdigit() and int(ch) != horse:
            return group, tuple(sorted((horse, int(ch))))
    elif page == "Both" and ch.isdigit() and int(ch) != horse:
        return "쌍승식", (int(ch), horse)  # header: row=2nd, column=1st
    elif page == "Bc" and ch.isdigit() and int(ch) != horse:
        return "복연승식", tuple(sorted((horse, int(ch))))
    elif page == "3Bc" and variant.isdigit() and ch.isdigit():
        combo = tuple(sorted((int(variant), horse, int(ch))))
        if len(set(combo)) == 3:
            return "삼복승식", combo
    elif page == "3Both" and variant.isdigit() and ch.isdigit():
        combo = (int(variant), int(ch), horse)  # fixed=1st, column=2nd, row=3rd
        if len(set(combo)) == 3:
            return "삼쌍승식", combo
    return None


def _could_pay(pool: str, combination: tuple[int, ...], arrival: list[int]) -> bool:
    if len(arrival) < 3:
        return False
    if pool == "단승식":
        return combination == (arrival[0],)
    if pool == "연승식":
        # KRA defines two winning places with fewer than eight runners and
        # three otherwise.  This is only an eligibility filter: the detailed
        # result table is still authoritative because an eligible placing can
        # have no paid dividend when no winning ticket was sold.
        n_paid = 3 if len(arrival) >= 8 else 2
        return combination[0] in arrival[:n_paid]
    if pool == "복승식":
        return combination == tuple(sorted(arrival[:2]))
    if pool == "쌍승식":
        return combination == tuple(arrival[:2])
    if pool == "복연승식":
        return set(combination).issubset(arrival[:3])
    if pool == "삼복승식":
        return combination == tuple(sorted(arrival[:3]))
    if pool == "삼쌍승식":
        return combination == tuple(arrival[:3])
    return False


def capped_candidates(data: pathlib.Path, races: dict[str, dict]) -> list[CappedCandidate]:
    found: set[CappedCandidate] = set()
    for page in ("Scm", "Both", "Bc", "3Bc", "3Both"):
        partitions = sorted((data / "cells" / f"page_key={page}").glob("*.csv.gz"))
        if not partitions:
            raise FileNotFoundError(f"no {page} partitions below {data}")
        print(f"scan {page}: {len(partitions)} partitions", file=sys.stderr)
        for path in partitions:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if row["section"] != "body" or row["cell_raw"] != str(DISPLAY_CAP):
                        continue
                    parsed = _grid_combination(row)
                    race = races.get(row["race_id"])
                    if parsed is None or race is None:
                        continue
                    pool, combo = parsed
                    if _could_pay(pool, combo, race.get("arrival") or []):
                        found.add(CappedCandidate(row["race_id"], pool, combo))
    return sorted(found)


def _decode_html(body: bytes) -> str:
    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("unknown KRA response encoding")


def fetch_html(
    race_id: str,
    cache_dir: pathlib.Path,
    *,
    timeout: float,
    retries: int,
    refresh: bool,
) -> tuple[str, bool]:
    cached = cache_dir / f"{race_id}.html"
    if cached.exists() and not refresh:
        return _decode_html(cached.read_bytes()), False
    request = urllib.request.Request(detail_url(race_id), headers={"User-Agent": USER_AGENT})
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            html = _decode_html(body)
            parse_winning_dividends(html)  # reject transient placeholder pages
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(body)
            return html, True
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"{race_id}: failed after {retries + 1} attempts: {last_error}")


def _sales_won(race: dict, pool: str) -> int:
    raw = (race.get("sales") or {}).get(pool, "")
    digits = "".join(c for c in str(raw) if c.isdigit())
    if not digits:
        raise ValueError(f"{race['race_id']}: missing {pool} sales")
    return int(digits)


FIELDS = [
    "race_id", "race_date", "meet", "race_no", "pool", "pool_label",
    "first_no", "second_no", "third_no", "grid_odds", "actual_odds",
    "is_above_display_cap", "sales_won", "payout_fraction",
    "ticket_inference_supported", "ticket_count_min", "ticket_count_max",
    "ticket_count_candidates", "ticket_count", "source_url",
]


def build_row(
    candidate: CappedCandidate,
    payout: WinningDividend,
    race: dict,
    *,
    n_pool_payouts: int,
) -> dict[str, object]:
    info = POOL[candidate.pool]
    sales = _sales_won(race, candidate.pool)
    # Place and quinella-place split one pool across several winning tickets;
    # likewise a dead heat creates multiple payouts.  Their ticket counts do
    # not follow the one-winner formula and are intentionally left blank.
    supported = candidate.pool not in MULTI_PAYOUT and n_pool_payouts == 1
    candidates = (
        ticket_candidates(sales, payout.odds, take_fraction=info["take"])
        if supported
        else range(0)
    )
    combo = list(candidate.combination) + [""] * (3 - len(candidate.combination))
    return {
        "race_id": candidate.race_id,
        "race_date": race["date"],
        "meet": race["meet"],
        "race_no": race["race_no"],
        "pool": info["key"],
        "pool_label": candidate.pool,
        "first_no": combo[0],
        "second_no": combo[1],
        "third_no": combo[2],
        "grid_odds": str(DISPLAY_CAP),
        "actual_odds": str(payout.odds),
        "is_above_display_cap": int(payout.odds > DISPLAY_CAP),
        "sales_won": sales,
        "payout_fraction": str(Decimal(info["take"].numerator) / info["take"].denominator),
        "ticket_inference_supported": int(supported),
        "ticket_count_min": candidates.start if len(candidates) else "",
        "ticket_count_max": candidates.stop - 1 if len(candidates) else "",
        "ticket_count_candidates": len(candidates) if supported else "",
        "ticket_count": candidates.start if len(candidates) == 1 else "",
        "source_url": detail_url(candidate.race_id),
    }


def write_csv_gz(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
        tmp = pathlib.Path(raw.name)
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--out", type=pathlib.Path,
        default=pathlib.Path("데이터/winning_capped_payouts.csv.gz"),
    )
    parser.add_argument(
        "--cache-dir", type=pathlib.Path,
        default=pathlib.Path("outputs/winning_payout_html"),
    )
    parser.add_argument("--race-id", action="append", default=[])
    parser.add_argument("--limit-races", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    races_path = args.data / "races.jsonl.gz"
    if not races_path.exists():
        sys.exit(f"missing {races_path}")
    races = load_races(races_path)
    candidates = capped_candidates(args.data, races)
    print("potential capped payouts:", dict(Counter(x.pool for x in candidates)), file=sys.stderr)

    by_race: dict[str, list[CappedCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_race[candidate.race_id].append(candidate)
    race_ids = sorted(by_race)
    if args.race_id:
        wanted = set(args.race_id)
        missing = wanted - set(race_ids)
        if missing:
            sys.exit(f"no potentially capped winning payout: {sorted(missing)}")
        race_ids = [race_id for race_id in race_ids if race_id in wanted]
    if args.limit_races:
        race_ids = race_ids[: args.limit_races]
    print(f"detail pages needed: {len(race_ids):,}", file=sys.stderr)

    rows = []
    unmatched = []
    problems = []
    for index, race_id in enumerate(race_ids, 1):
        try:
            html, used_network = fetch_html(
                race_id, args.cache_dir, timeout=args.timeout,
                retries=args.retries, refresh=args.refresh,
            )
            payouts = parse_winning_dividends(html)
            payout_counts = Counter(p.pool for p in payouts)
            page = {(p.pool, _canonical(p.pool, p.combination)): p for p in payouts}
            for candidate in by_race[race_id]:
                payout = page.get((candidate.pool, candidate.combination))
                if payout is None:
                    unmatched.append(candidate)
                    continue
                rows.append(
                    build_row(
                        candidate, payout, races[race_id],
                        n_pool_payouts=payout_counts[candidate.pool],
                    )
                )
            if used_network and args.delay > 0:
                time.sleep(args.delay)
        except Exception as exc:
            problems.append({"race_id": race_id, "error": str(exc)})
        if index % 10 == 0 or index == len(race_ids):
            print(
                f"  [{index}/{len(race_ids)}] rows={len(rows)} "
                f"unmatched={len(unmatched)} problems={len(problems)}",
                file=sys.stderr,
            )

    if problems:
        for problem in problems:
            print(json.dumps(problem, ensure_ascii=False), file=sys.stderr)
        sys.exit(f"refusing partial output: {len(problems)} detail page(s) failed")

    rows.sort(key=lambda row: (str(row["race_id"]), str(row["pool"])))
    write_csv_gz(args.out, rows)
    print(f"wrote {args.out}: {len(rows):,} rows", file=sys.stderr)
    print("recovered by pool:", dict(Counter(row["pool_label"] for row in rows)))
    print("actual > 9999.9:", sum(int(row["is_above_display_cap"]) for row in rows))
    print("unmatched potential cells:", len(unmatched))
    for candidate in unmatched:
        print("  unmatched:", candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
