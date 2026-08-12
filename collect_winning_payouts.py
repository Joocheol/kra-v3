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
import hashlib
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
from decimal import Decimal, ROUND_HALF_UP
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
    "단승식": {"key": "win", "page": "Scm", "take": Fraction(80, 100), "m": 1},
    "연승식": {"key": "place", "page": "Scm", "take": Fraction(80, 100), "m": 1},
    "복승식": {"key": "quinella", "page": "Scm", "take": Fraction(73, 100), "m": 1},
    "쌍승식": {"key": "exacta", "page": "Both", "take": Fraction(73, 100), "m": 1},
    # One quinella-place purchase creates three winning-pair claims; its
    # accounting multiplier is therefore three, not one.
    "복연승식": {"key": "quinella_place", "page": "Bc", "take": Fraction(73, 100), "m": 3},
    "삼복승식": {"key": "trio", "page": "3Bc", "take": Fraction(73, 100), "m": 1},
    "삼쌍승식": {"key": "trifecta", "page": "3Both", "take": Fraction(73, 100), "m": 1},
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


def load_frozen_payouts(
    cache_dir: pathlib.Path,
) -> dict[tuple[str, str, tuple[int, ...]], Decimal]:
    expected: dict[tuple[str, str, tuple[int, ...]], Decimal] = {}
    for path in sorted(cache_dir.glob("*.html")):
        race_id = path.stem
        for payout in parse_winning_dividends(_decode_html(path.read_bytes())):
            key = (race_id, payout.pool, _canonical(payout.pool, payout.combination))
            if key in expected and expected[key] != payout.odds:
                raise ValueError(f"duplicate payout with different odds: {key}")
            expected[key] = payout.odds
    if not expected:
        raise ValueError(f"no frozen detail pages in {cache_dir}")
    return expected


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


def _could_pay(
    pool: str,
    combination: tuple[int, ...],
    arrival: list[int],
    starters: int | None = None,
) -> bool:
    if not arrival:
        return False
    if pool == "단승식":
        return combination == (arrival[0],)
    if pool == "연승식":
        # KRA defines two winning places with fewer than eight runners and
        # three otherwise.  This is only an eligibility filter: the detailed
        # result table is still authoritative because an eligible placing can
        # have no paid dividend when no winning ticket was sold.
        n_paid = 3 if (starters if starters is not None else len(arrival)) >= 8 else 2
        return combination[0] in arrival[:n_paid]
    if len(arrival) < 3:
        return False
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


def capped_candidates(
    data: pathlib.Path,
    races: dict[str, dict],
    *,
    orientation_expected: dict[tuple[str, str, tuple[int, ...]], Decimal] | None = None,
    orientation_found: dict[tuple[str, str, tuple[int, ...]], Decimal] | None = None,
) -> list[CappedCandidate]:
    found: set[CappedCandidate] = set()
    wanted_races = {key[0] for key in orientation_expected or {}}
    for page in ("Scm", "Both", "Bc", "3Bc", "3Both"):
        partitions = sorted((data / "cells" / f"page_key={page}").glob("*.csv.gz"))
        if not partitions:
            raise FileNotFoundError(f"no {page} partitions below {data}")
        print(f"scan {page}: {len(partitions)} partitions", file=sys.stderr)
        for path in partitions:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if row["section"] != "body" or row["spanned"] != "0":
                        continue
                    parsed = _grid_combination(row)
                    race = races.get(row["race_id"])
                    if parsed is None or race is None:
                        continue
                    pool, combo = parsed
                    key = (row["race_id"], pool, _canonical(pool, combo))
                    if (
                        orientation_expected is not None
                        and orientation_found is not None
                        and row["race_id"] in wanted_races
                        and key in orientation_expected
                        and row["cell_raw"].replace(".", "", 1).isdigit()
                    ):
                        value = Decimal(row["cell_raw"])
                        if key in orientation_found and orientation_found[key] != value:
                            raise ValueError(f"grid mapping is not unique: {key}")
                        orientation_found[key] = value
                    if row["cell_raw"] != str(DISPLAY_CAP):
                        continue
                    starters = len(race["horses"]) - len(race.get("scratched") or [])
                    if _could_pay(pool, combo, race.get("arrival") or [], starters):
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
    offline: bool,
) -> tuple[str, bool]:
    cached = cache_dir / f"{race_id}.html"
    if cached.exists() and not refresh:
        return _decode_html(cached.read_bytes()), False
    if offline:
        raise FileNotFoundError(f"offline source is missing: {cached}")
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
    "pool_multiplier", "ticket_inference_supported", "ticket_inference_status",
    "ticket_count_min", "ticket_count_max",
    "ticket_count_candidates", "ticket_count", "source_url",
]
UNMATCHED_FIELDS = ["race_id", "pool", "combination", "reason"]
ORIENTATION_FIELDS = [
    "pool", "source_payouts", "grid_cells_found", "odds_equal",
    "unexplained_odds_mismatches", "failures",
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
        ticket_candidates(
            sales, payout.odds, take_fraction=info["take"],
            pool_multiplier=info["m"],
        )
        if supported
        else range(0)
    )
    if supported and not candidates:
        raise ValueError(
            f"{candidate.race_id} {candidate.pool} {candidate.combination}: "
            "paid dividend has no accounting-consistent integer ticket count"
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
        "pool_multiplier": info["m"],
        "ticket_inference_supported": int(supported),
        "ticket_inference_status": "identified" if supported else "unsupported_multi_payout",
        "ticket_count_min": candidates.start if len(candidates) else "",
        "ticket_count_max": candidates.stop - 1 if len(candidates) else "",
        "ticket_count_candidates": len(candidates) if supported else "",
        "ticket_count": candidates.start if len(candidates) == 1 else "",
        "source_url": detail_url(candidate.race_id),
    }


def write_csv_gz(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    write_dicts_gz(path, rows, FIELDS)


def write_dicts_gz(
    path: pathlib.Path,
    rows: list[dict[str, object]],
    fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
        tmp = pathlib.Path(raw.name)
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
    tmp.replace(path)


def audit_grid_orientation(
    expected: dict[tuple[str, str, tuple[int, ...]], Decimal],
    found: dict[tuple[str, str, tuple[int, ...]], Decimal],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Verify every grid-axis mapping against frozen real winning payouts."""
    failures = []
    stats = defaultdict(Counter)
    for key, actual in sorted(expected.items()):
        race_id, pool, combo = key
        stats[pool]["source"] += 1
        grid = found.get(key)
        if grid is not None:
            stats[pool]["found"] += 1
        expected_grid = min(
            actual.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), DISPLAY_CAP
        )
        if grid == expected_grid:
            stats[pool]["equal"] += 1
        else:
            stats[pool]["mismatch"] += 1
            failures.append({
                "race_id": race_id,
                "pool": pool,
                "combination": "-".join(map(str, combo)),
                "reason": f"source={actual}; grid={grid}",
            })
    rows = []
    for pool in POOL:
        count = stats[pool]
        rows.append({
            "pool": pool,
            "source_payouts": count["source"],
            "grid_cells_found": count["found"],
            "odds_equal": count["equal"],
            "unexplained_odds_mismatches": count["mismatch"],
            "failures": count["source"] - count["found"],
        })
    return rows, failures


def make_report(
    rows: list[dict[str, object]],
    unmatched: list[dict[str, object]],
    orientation: list[dict[str, object]],
    source_pages: int,
) -> str:
    by_pool = Counter(str(row["pool_label"]) for row in rows)
    above = [row for row in rows if int(row["is_above_display_cap"])]
    inferred = [row for row in rows if row["ticket_inference_status"] == "identified"]
    lines = [
        "# KRA 상세 성적표에서 복원한 상한 초과 지급배당",
        "",
        "## 재현 결과",
        "",
        f"동결한 실제 KRA 상세 성적표 {source_pages:,}개를 오프라인으로 읽어 "
        f"배당판 `9999.9` 셀과 일치하는 지급배당 {len(rows):,}건을 복원했다. "
        f"실제 지급배당이 9999.9를 초과한 것은 {len(above):,}건이다.",
        "",
        "| 승식 | 복원 건수 |",
        "| --- | ---: |",
    ]
    for pool in POOL:
        lines.append(f"| {pool} | {by_pool[pool]:,} |")
    lines.extend([
        "",
        "요청한 상세 페이지 수와 지급배당 건수는 다른 통계다. 한 상세 페이지에서 "
        "삼복승과 삼쌍승의 상한 초과 지급이 함께 복원될 수 있다. 고배당에서는 "
        "반올림 구간 폭이 좁으므로 점식별은 대체로 기계적이며, 복원 모형의 성과가 아니다.",
        "",
        f"정수 마권 수 추론을 지원하는 {len(inferred):,}건은 모두 양립하는 후보가 "
        "존재한다. 지원되는 행에서 후보가 0개이면 스크립트가 즉시 실패한다. "
        f"상세표에 지급항목이 없던 잠재 셀 {len(unmatched):,}건은 별도 산출물에 남겼다.",
        "",
        "## 격자 방향성의 실제 자료 검증",
        "",
        "각 승식의 실제 당첨조합을 행·열·고정마 축으로 역매핑하고, 미검열 배당은 "
        "실제 지급배당과 같고 상한 초과 배당은 `9999.9`인지 확인했다.",
        "",
        "| 승식 | 상세표 지급항목 | 격자 셀 발견 | 배당 일치 | 미해명 배당불일치 | 축 매핑 실패 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in orientation:
        lines.append(
            f"| {row['pool']} | {row['source_payouts']:,} | "
            f"{row['grid_cells_found']:,} | {row['odds_equal']:,} | "
            f"{row['unexplained_odds_mismatches']:,} | {row['failures']:,} |"
        )
    lines.extend([
        "",
        "2016-07-01 제주 8경주의 연승식 두 셀은 격자 `1.0`과 공식 지급배당 "
        "1.5·1.3이 일치하지 않는다. `1.0`을 근거 없는 하한코드로 재분류하지 않고 "
        "미해명 배당불일치로 계상했다. 조합 위치는 모두 발견되어 축 매핑 실패는 아니다.",
        "",
        "같은 경주의 3착 3번 말은 8두 출주라 연승식 지급 자격이 있지만 격자는 "
        "`9999.9`, 공식 상세표에는 지급항목이 없다. 이는 무투표 해석과 일치하는 "
        "직접 사례지만, 2016년 격자와 최종 배당의 시점 불일치가 함께 관측되므로 "
        "인코딩 규정의 결정적 증명으로 사용하지 않는다.",
        "",
        "## 표본의 범위",
        "",
        "이 표본은 실제 착순을 이용해 요청 대상을 좁힌 검증표본이므로 전체 검열 셀을 "
        "대표하지 않는다. 출주두수는 완주두수가 아니라 취소마를 제외한 출주두수로 "
        "판정한다. 저장된 선형 착순만으로 발견할 수 없는 공동착 경주가 있을 수 있어 "
        "복원 건수는 전수 상한이 아니라 확인된 하한으로 해석한다.",
        "",
        "원천 HTML, 원천 해시, 미매칭 목록, 방향성 감사표와 최종 CSV를 모두 저장해 "
        "네트워크 없이 재생성할 수 있다.",
        "",
    ])
    return "\n".join(lines)


def write_source_manifest(cache_dir: pathlib.Path, path: pathlib.Path) -> None:
    lines = []
    for source in sorted(cache_dir.glob("*.html")):
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        lines.append(f"{digest}  {cache_dir.name}/{source.name}")
    if not lines:
        raise ValueError(f"no HTML sources in {cache_dir}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--out", type=pathlib.Path,
        default=pathlib.Path("데이터/winning_capped_payouts.csv.gz"),
    )
    parser.add_argument(
        "--cache-dir", type=pathlib.Path,
        default=pathlib.Path("데이터/winning_payout_html"),
    )
    parser.add_argument(
        "--unmatched-out", type=pathlib.Path,
        default=pathlib.Path("데이터/winning_payout_unmatched.csv.gz"),
    )
    parser.add_argument(
        "--orientation-out", type=pathlib.Path,
        default=pathlib.Path("데이터/grid_orientation_audit.csv.gz"),
    )
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/winning_capped_payouts.md"),
    )
    parser.add_argument(
        "--source-manifest", type=pathlib.Path,
        default=pathlib.Path("데이터/winning_payout_html.sha256"),
    )
    parser.add_argument("--race-id", action="append", default=[])
    parser.add_argument("--limit-races", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--offline", action="store_true",
        help="require every detailed result page to exist in --cache-dir",
    )
    args = parser.parse_args()

    races_path = args.data / "races.jsonl.gz"
    if not races_path.exists():
        sys.exit(f"missing {races_path}")
    races = load_races(races_path)
    orientation_expected = load_frozen_payouts(args.cache_dir)
    orientation_found: dict[tuple[str, str, tuple[int, ...]], Decimal] = {}
    candidates = capped_candidates(
        args.data, races,
        orientation_expected=orientation_expected,
        orientation_found=orientation_found,
    )
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
                offline=args.offline,
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
    unmatched_rows = [
        {
            "race_id": item.race_id,
            "pool": item.pool,
            "combination": "-".join(map(str, item.combination)),
            "reason": "eligible capped grid cell absent from detailed paid-dividend table",
        }
        for item in sorted(unmatched)
    ]
    orientation, orientation_failures = audit_grid_orientation(
        orientation_expected, orientation_found
    )
    mapping_failures = [
        failure for failure in orientation_failures
        if failure["reason"].endswith("grid=None")
    ]
    for failure in orientation_failures[:20]:
        print("orientation discrepancy:", failure, file=sys.stderr)
    if mapping_failures:
        sys.exit(f"refusing output: {len(mapping_failures)} grid mapping failures")
    write_csv_gz(args.out, rows)
    write_dicts_gz(args.unmatched_out, unmatched_rows, UNMATCHED_FIELDS)
    write_dicts_gz(args.orientation_out, orientation, ORIENTATION_FIELDS)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    source_pages = len(list(args.cache_dir.glob("*.html")))
    args.report.write_text(
        make_report(rows, unmatched_rows, orientation, source_pages),
        encoding="utf-8",
    )
    write_source_manifest(args.cache_dir, args.source_manifest)
    print(f"wrote {args.out}: {len(rows):,} rows", file=sys.stderr)
    print(f"wrote {args.unmatched_out}: {len(unmatched_rows):,} rows", file=sys.stderr)
    print(f"wrote {args.orientation_out}: {len(orientation):,} pools", file=sys.stderr)
    print(f"wrote {args.report}", file=sys.stderr)
    print(f"wrote {args.source_manifest}", file=sys.stderr)
    print("recovered by pool:", dict(Counter(row["pool_label"] for row in rows)))
    print("actual > 9999.9:", sum(int(row["is_above_display_cap"]) for row in rows))
    print("unmatched potential cells:", len(unmatched))
    for candidate in unmatched:
        print("  unmatched:", candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
