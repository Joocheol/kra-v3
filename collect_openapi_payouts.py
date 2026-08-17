#!/usr/bin/env python3
"""Collect KRA API179 realized payouts and audit unpaid winning combinations.

The archived betting grids in this repository preserve the display cap 9999.9.
API179 is a separate official source: it returns race/pool turnover and the
realized dividend text.  This collector keeps the sources separate, finds the
largest actually paid dividend in every pool, and compares paid combinations
with the archived finish order to identify *candidates* for zero winning bets.

Example:

    DATA_GO_KR_SERVICE_KEY=... python3 collect_openapi_payouts.py \
        --start-year 2016 --end-year 2025 --out outputs/openapi179

Only the standard library is required.  The service key is never written or
printed.  Output gzip files are deterministic (mtime=0).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import itertools
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from decimal import Decimal
from fractions import Fraction

from kra.results import ticket_candidates

ENDPOINT = "https://apis.data.go.kr/B551015/API179_1/salesAndDividendRate_1"
MEET_NAMES = {1: "서울", 2: "제주", 3: "부경"}
POOL_LABELS = {
    "단식": "단승식",
    "연식": "연승식",
    "복식": "복승식",
    "쌍식": "쌍승식",
    "복연": "복연승식",
    "삼복": "삼복승식",
    "삼쌍": "삼쌍승식",
}
POOL_ORDER = tuple(POOL_LABELS.values())
POOL_SIZE = {
    "단승식": 1,
    "연승식": 1,
    "복승식": 2,
    "쌍승식": 2,
    "복연승식": 2,
    "삼복승식": 3,
    "삼쌍승식": 3,
}
UNORDERED_POOLS = {"복승식", "복연승식", "삼복승식"}
TAKE_FRACTION = {
    "단승식": Fraction(80, 100),
    "연승식": Fraction(80, 100),
    "복승식": Fraction(73, 100),
    "쌍승식": Fraction(73, 100),
    "복연승식": Fraction(73, 100),
    "삼복승식": Fraction(73, 100),
    "삼쌍승식": Fraction(73, 100),
}
POOL_MULTIPLIER = {"복연승식": 3}
_HORSE_TOKEN = r"(?:[\u2460-\u2473]|\([0-9]{1,2}\))"
_HORSE_TOKEN_RE = re.compile(_HORSE_TOKEN)
_PAYOUT_RE = re.compile(
    rf"(?P<combo>(?:{_HORSE_TOKEN}\s*)+)\s*-\s*"
    r"(?P<odds>[0-9][0-9,]*(?:\.[0-9]+)?)"
)
_PLACEHOLDER_RE = re.compile(r"^(?:ⓩ\s*){1,3}-[0-9]*(?:\.[0-9]+)?$")

ROW_FIELDS = [
    "race_id", "rc_date", "meet", "meet_name", "rc_no", "pool",
    "turnover_won", "raw_odds", "payout_count", "max_odds",
]
PAYOUT_FIELDS = [
    "race_id", "rc_date", "meet", "meet_name", "rc_no", "pool",
    "turnover_won", "combination", "actual_odds", "ticket_candidates_count",
    "ticket_count_min", "ticket_count_max", "ticket_count_exact",
]
MISSING_FIELDS = [
    "race_id", "date", "meet", "meet_name", "race_no", "pool",
    "turnover_won", "expected_combination", "paid_combinations", "raw_odds",
    "candidate_class", "warning",
]


def horse_number(token: str) -> int:
    value = int(token[1:-1]) if token.startswith("(") else ord(token) - 0x245F
    if not 1 <= value <= 20:
        raise ValueError(f"not a horse number token: {token!r}")
    return value


def parse_odds(raw: object, pool: str) -> list[tuple[tuple[int, ...], Decimal]]:
    """Parse API179 text such as ``⑮③④-391736.8``."""
    text = "" if raw is None else str(raw).strip()
    # API179 uses ⓩ as a non-horse placeholder in a small set of abnormal
    # 2020--2021 rows (including zero-turnover and sub-1 refund-like values).
    # It is not a paid winning combination.
    if _PLACEHOLDER_RE.fullmatch(text):
        return []
    out: list[tuple[tuple[int, ...], Decimal]] = []
    for match in _PAYOUT_RE.finditer(text):
        combo = tuple(horse_number(token) for token in _HORSE_TOKEN_RE.findall(match["combo"]))
        if len(combo) != POOL_SIZE[pool]:
            raise ValueError(
                f"{pool}: expected {POOL_SIZE[pool]} horses, got {combo!r} in {text!r}"
            )
        out.append((combo, Decimal(match["odds"].replace(",", ""))))
    if text and not out:
        raise ValueError(f"could not parse API179 odds for {pool}: {text!r}")
    return out


def canonical(pool: str, combo: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted(combo)) if pool in UNORDERED_POOLS else combo


def year_range(start: int, end: int) -> list[int]:
    if not (2000 <= start <= end <= 2100):
        raise ValueError(f"invalid year range: {start}..{end}")
    return list(range(start, end + 1))


def _request_json(params: dict[str, object], *, retries: int = 4) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        ENDPOINT + "?" + query,
        headers={"User-Agent": "kra-v3-openapi179-audit/1.0"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read())
            header = payload.get("response", {}).get("header", {})
            if str(header.get("resultCode", "")) != "00":
                raise RuntimeError(
                    f"OpenAPI error {header.get('resultCode')}: {header.get('resultMsg')}"
                )
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"API179 request failed after {retries} attempts: {exc}") from exc
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def _items(payload: dict) -> tuple[list[dict], int]:
    body = payload.get("response", {}).get("body", {})
    wrapped = body.get("items") or {}
    items = wrapped.get("item", []) if isinstance(wrapped, dict) else []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise ValueError(f"unexpected API179 items type: {type(items).__name__}")
    return items, int(body.get("totalCount") or len(items))


def fetch_year(
    service_key: str, year: int, meet: int, rows_per_page: int = 1000
) -> tuple[list[dict], int]:
    page, out = 1, []
    while True:
        payload = _request_json({
            "ServiceKey": service_key,
            "pageNo": page,
            "numOfRows": rows_per_page,
            "meet": meet,
            "rc_year": year,
            "_type": "json",
        })
        items, total = _items(payload)
        out.extend(items)
        if len(out) >= total or not items:
            return out, page
        page += 1


def normalize_rows(raw_rows: list[dict]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    payouts: list[dict[str, object]] = []
    for item in raw_rows:
        short_pool = str(item.get("pool", "")).strip()
        if short_pool not in POOL_LABELS:
            raise ValueError(f"unknown API179 pool label: {short_pool!r}")
        pool = POOL_LABELS[short_pool]
        date = str(item["rcDate"])
        meet = int(item["meet"])
        race_no = int(item["rcNo"])
        turnover = int(item.get("amt") or 0)
        raw_odds = str(item.get("odds") or "").strip()
        parsed = parse_odds(raw_odds, pool)
        race_id = f"{date[:4]}-{date[4:6]}-{date[6:]}_{meet}_{race_no:02d}"
        rows.append({
            "race_id": race_id,
            "rc_date": date,
            "meet": meet,
            "meet_name": MEET_NAMES.get(meet, str(meet)),
            "rc_no": race_no,
            "pool": pool,
            "turnover_won": turnover,
            "raw_odds": raw_odds,
            "payout_count": len(parsed),
            "max_odds": max((odds for _, odds in parsed), default=""),
        })
        candidates: range | tuple[()] = ()
        if len(parsed) == 1 and pool not in {"연승식", "복연승식"}:
            candidates = ticket_candidates(
                turnover,
                parsed[0][1],
                take_fraction=TAKE_FRACTION[pool],
                pool_multiplier=POOL_MULTIPLIER.get(pool, 1),
            )
        for combo, odds in parsed:
            count = len(candidates) if len(parsed) == 1 else 0
            low = candidates.start if count else ""
            high = candidates.stop - 1 if count else ""
            payouts.append({
                "race_id": race_id,
                "rc_date": date,
                "meet": meet,
                "meet_name": MEET_NAMES.get(meet, str(meet)),
                "rc_no": race_no,
                "pool": pool,
                "turnover_won": turnover,
                "combination": "-".join(map(str, combo)),
                "actual_odds": odds,
                "ticket_candidates_count": count,
                "ticket_count_min": low,
                "ticket_count_max": high,
                "ticket_count_exact": low if count == 1 else "",
            })
    rows.sort(key=lambda r: (r["rc_date"], r["meet"], r["rc_no"], POOL_ORDER.index(r["pool"])))
    payouts.sort(key=lambda r: (r["rc_date"], r["meet"], r["rc_no"], POOL_ORDER.index(r["pool"]), r["combination"]))
    return rows, payouts


def load_races(path: pathlib.Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def _active_starters(race: dict) -> int:
    registered = race.get("n_registered")
    scratched = race.get("scratched") or []
    if registered is not None:
        return int(registered) - len(scratched)
    horses = race.get("horses") or []
    return len(horses) - len(scratched)


def expected_combinations(race: dict, pool: str) -> list[tuple[int, ...]]:
    arrival = tuple(int(x) for x in (race.get("arrival") or []))
    need = 3 if pool in {"복연승식", "삼복승식", "삼쌍승식"} else 2
    if pool in {"단승식", "연승식"}:
        need = 1
    if len(arrival) < need:
        return []
    if pool == "단승식":
        return [(arrival[0],)]
    if pool == "연승식":
        paid_places = 2 if _active_starters(race) <= 7 else 3
        return [(horse,) for horse in arrival[:paid_places]]
    if pool == "복승식":
        return [tuple(sorted(arrival[:2]))]
    if pool == "쌍승식":
        return [arrival[:2]]
    if pool == "복연승식":
        return [tuple(sorted(pair)) for pair in itertools.combinations(arrival[:3], 2)]
    if pool == "삼복승식":
        return [tuple(sorted(arrival[:3]))]
    if pool == "삼쌍승식":
        return [arrival[:3]]
    raise ValueError(f"unknown pool: {pool}")


def find_missing_candidates(
    races: list[dict], rows: list[dict[str, object]], payouts: list[dict[str, object]]
) -> list[dict[str, object]]:
    row_index = {(r["race_id"], r["pool"]): r for r in rows}
    paid: dict[tuple[object, object], set[tuple[int, ...]]] = {}
    for payout in payouts:
        key = (payout["race_id"], payout["pool"])
        combo = tuple(int(x) for x in str(payout["combination"]).split("-"))
        paid.setdefault(key, set()).add(canonical(str(payout["pool"]), combo))

    out: list[dict[str, object]] = []
    for race in races:
        for pool in POOL_ORDER:
            key = (race.get("race_id"), pool)
            api_row = row_index.get(key)
            # Absence of an API row may mean that the pool was not offered.
            # It is not evidence of zero tickets, so do not emit a candidate.
            if api_row is None or int(api_row["turnover_won"]) <= 0:
                continue
            expected = expected_combinations(race, pool)
            if not expected:
                continue
            observed = paid.get(key, set())
            for combo in expected:
                normalized = canonical(pool, combo)
                if normalized in observed:
                    continue
                out.append({
                    "race_id": race["race_id"],
                    "date": race.get("date", str(race["race_id"])[:10]),
                    "meet": str(race["race_id"]).split("_")[1],
                    "meet_name": race.get("meet_name", ""),
                    "race_no": race.get("race_no", int(str(race["race_id"]).split("_")[2])),
                    "pool": pool,
                    "turnover_won": api_row["turnover_won"],
                    "expected_combination": "-".join(map(str, combo)),
                    "paid_combinations": " ".join(
                        "-".join(map(str, value)) for value in sorted(observed)
                    ),
                    "raw_odds": api_row["raw_odds"],
                    "candidate_class": (
                        "expected_combination_unpaid" if observed else "pool_odds_empty"
                    ),
                    "warning": "공동착·승식취소·착순 파싱 이상은 API155/상세성적표로 재확인 필요",
                })
    out.sort(key=lambda r: (r["date"], int(r["meet"]), int(r["race_no"]), POOL_ORDER.index(r["pool"]), r["expected_combination"]))
    return out


def write_csv(path: pathlib.Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
            tmp = pathlib.Path(raw.name)
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
                with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                    writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
        tmp.replace(path)
    else:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


def write_jsonl_gz(path: pathlib.Path, rows: list[dict]) -> None:
    """Preserve raw API rows before parsing so a format error is diagnosable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
        tmp = pathlib.Path(raw.name)
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                for row in rows:
                    text.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def read_jsonl_gz(path: pathlib.Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def maxima(payouts: list[dict[str, object]]) -> list[dict[str, object]]:
    out = []
    for pool in POOL_ORDER:
        matches = [row for row in payouts if row["pool"] == pool]
        if not matches:
            continue
        maximum = max(matches, key=lambda r: Decimal(str(r["actual_odds"])))
        out.append(dict(maximum))
    return out


def write_report(
    path: pathlib.Path,
    rows: list[dict[str, object]],
    payouts: list[dict[str, object]],
    maximum_rows: list[dict[str, object]],
    missing: list[dict[str, object]],
    start_year: int,
    end_year: int,
    request_count: int,
) -> None:
    races = {(r["race_id"]) for r in rows}
    over_cap = sum(Decimal(str(p["actual_odds"])) > Decimal("9999.9") for p in payouts)
    lines = [
        "# KRA API179 실현배당 전수 점검",
        "",
        f"- 요청기간: `{start_year}`–`{end_year}`",
        f"- API 호출: {request_count:,}회 (연도·경마장 조회 후 자동 페이지네이션)",
        f"- API179 수록 경주: {len(races):,}개",
        f"- 경주·승식 행: {len(rows):,}개",
        f"- 실현 지급배당: {len(payouts):,}개",
        f"- 9999.9 초과 실현 지급배당: {over_cap:,}개",
        f"- 무투표 후보: {len(missing):,}개",
        "",
        "## 승식별 최대 실현 배당",
        "",
        "| 승식 | 배당률 | 경주 | 조합 | 매출액 | 추론 마권수 |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for row in maximum_rows:
        exact = row["ticket_count_exact"] or "다중지급/구간"
        lines.append(
            f"| {row['pool']} | {row['actual_odds']} | {row['race_id']} | "
            f"{row['combination']} | {int(row['turnover_won']):,}원 | {exact} |"
        )
    lines += [
        "",
        "## 무투표 후보",
        "",
        "API179에 해당 승식의 양수 매출 행은 있으나, 보존된 실제 착순으로부터 "
        "계산한 당첨조합이 지급배당 문자열에 없는 경우다. 이 조건은 강한 단서지만 "
        "공동착, 승식 취소, 원자료 착순 파싱 이상을 배제하지 못하므로 후보로 표시한다.",
        "",
        "| 승식 | 후보 수 |",
        "|---|---:|",
    ]
    counts = Counter(str(row["pool"]) for row in missing)
    for pool in POOL_ORDER:
        lines.append(f"| {pool} | {counts[pool]:,} |")
    if missing:
        lines += ["", "### 후보 목록", ""]
        for row in missing:
            lines.append(
                f"- `{row['race_id']}` {row['pool']} 조합 `{row['expected_combination']}` "
                f"(API 지급조합: `{row['paid_combinations'] or '없음'}`)"
            )
    lines += [
        "",
        "## 해석 제한",
        "",
        "- 실현 지급배당은 API179 값이며, 배당판의 `9999.9` 상한 셀과 구분한다.",
        "- 마권수는 단일 지급 승식에서만 100원 단위·공제율·한 자리 반올림으로 역산한다.",
        "- 연승식과 복연승식 등 다중 지급 승식은 개별 지급액만으로 마권수를 분리할 수 없어 비워 둔다.",
        "- API 행이 통째로 없는 승식은 미시행·취소 가능성이 있어 무투표로 분류하지 않는다.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--meets", default="1,2,3", help="comma-separated meet codes")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("outputs/openapi179"))
    parser.add_argument("--races", type=pathlib.Path, default=pathlib.Path("데이터/races.jsonl.gz"))
    parser.add_argument("--pause", type=float, default=0.05, help="seconds between base requests")
    parser.add_argument(
        "--resume", action="store_true",
        help="reuse completed year/meet checkpoints in the output directory",
    )
    args = parser.parse_args()

    key = urllib.parse.unquote(os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip())
    if len(key) <= 20:
        parser.error("DATA_GO_KR_SERVICE_KEY is missing or implausibly short")
    years = year_range(args.start_year, args.end_year)
    meets = [int(value) for value in args.meets.split(",")]
    if not meets or set(meets) - set(MEET_NAMES):
        parser.error("--meets must contain only 1,2,3")

    args.out.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = args.out / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    raw_rows = []
    total_groups = len(years) * len(meets)
    request_count = 0
    done = 0
    for year in years:
        for meet in meets:
            checkpoint = checkpoint_dir / f"{year}_{meet}.jsonl.gz"
            if args.resume and checkpoint.exists():
                batch = read_jsonl_gz(checkpoint)
                pages = 0
                source = "checkpoint"
            else:
                batch, pages = fetch_year(key, year, meet)
                write_jsonl_gz(checkpoint, batch)
                source = f"{pages} request(s)"
            raw_rows.extend(batch)
            request_count += pages
            done += 1
            print(
                f"[{done:>2}/{total_groups}] {year} {MEET_NAMES[meet]}: "
                f"{len(batch):>5} rows, {source}",
                file=sys.stderr,
            )
            if args.pause:
                time.sleep(args.pause)

    write_jsonl_gz(args.out / "openapi179_raw.jsonl.gz", raw_rows)
    rows, payouts = normalize_rows(raw_rows)
    maximum_rows = maxima(payouts)
    races = load_races(args.races)
    missing = find_missing_candidates(races, rows, payouts)

    write_csv(args.out / "openapi179_rows.csv.gz", rows, ROW_FIELDS)
    write_csv(args.out / "openapi179_payouts.csv.gz", payouts, PAYOUT_FIELDS)
    write_csv(args.out / "openapi179_maxima.csv", maximum_rows, PAYOUT_FIELDS)
    write_csv(args.out / "openapi179_missing_candidates.csv", missing, MISSING_FIELDS)
    write_report(
        args.out / "openapi179_report.md", rows, payouts, maximum_rows, missing,
        args.start_year, args.end_year, request_count,
    )
    print(f"wrote {args.out} ({len(rows):,} pool rows, {len(payouts):,} payouts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
