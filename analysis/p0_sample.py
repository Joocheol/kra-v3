#!/usr/bin/env python3
"""Fix the SPEC_P0 4.3 sample before any re-collection request is made.

Two phases, deliberately separated by a file on disk.

  strata   walk all 19,301 archive races and write outputs/p0/strata.csv,
           one row per race carrying the stratum variables of the 4.3 table.

  sample   read strata.csv (NOT the archive) and write outputs/p0/sample_38.json.

The second phase reads the CSV rather than recomputing the stratum variables,
because two computations of "registered field size" can drift apart while both
look right. The committed CSV is the single definition; sample_38.json records
its sha256 so the pair can be checked later.

Selection is deterministic: within a stratum, sort by sha256(race_id) ascending
and take the top k. No seed, no clock, no human choice. Re-running on the same
archive yields the same races.

SAMPLE SIZE FOLLOWS THE DESIGN. The size is an argument in a critique response
(SPEC_P0 4.3, r2-K7), so this script must never bend the strata to hit a round
number. Two of the 36 cross cells are empty in this archive, so the cross
contributes 34 and the sample is 38. Empty cells are written out with quota 0
rather than dropped. If a stratum cannot fill a quota it was given, the script
prints the observed distribution and exits non-zero without writing anything.

Stdlib only, like p0_probe.py: this runs before any parser exists.

Usage:
    python3 analysis/p0_sample.py --archive <path-to>/raw_collected_v3_15w
    python3 analysis/p0_sample.py --phase strata --archive <path>
    python3 analysis/p0_sample.py --phase sample          # archive not needed
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

# Reuse the archive reader that already exists rather than writing a second one.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from p0_probe import TABLE_RE, TD_RE, TR_RE, text  # noqa: E402

# --------------------------------------------------------------------------
# SPEC_P0 4.3 stratum table. Levels are literal from the spec; the derivations
# below say where in the archive each one is read.
# --------------------------------------------------------------------------
MEETS = [1, 2, 3]                       # 서울 1, 제주 2, 부산경남 3 (SPEC_P0 1)
YEARS = [2016, 2018, 2022, 2025]        # 개편, 2018 상한 해제 (SPEC_P0 4.3)
SIZE_BANDS = ["le7", "8to10", "ge11"]   # 등록두수 ≤7 / 8–10 / ≥11
COVERAGE = ["cancel", "theta"]          # 취소마 있음 / θ 인쇄 있음

# The sample size is NOT a constant. It is derived in build_sample() from the
# number of non-empty cross cells; see the quota rule there. Writing it as a
# constant here is what would let the design drift to fit the number.
TRANSCRIPT_N = 5                        # SPEC_P0 7절: 사람이 전수 전사 가능한 상한

RACE_ID_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d)_(\d+)$")
# A cell whose entire content is the censoring point. Anchored on the tag
# boundaries so that a longer number ending in 9999.9 cannot match.
THETA_CELL_RE = re.compile(r">\s*9999\.9\s*<")
DASH_RUN_RE = re.compile(r"^-{3,}$")    # '----' 취소, as against the single '-'
NUM_RE = re.compile(r"^\d+(?:\.\d+)?$")

STRATA_FIELDS = [
    "race_id", "year", "meet", "race_no",
    "n_registered", "size_band", "horse_nums_consecutive",
    "n_keys_3bc", "n_keys_3both",
    "cancel_notice", "has_cancel_dash",
    "theta_cells_base", "theta_cells_all", "has_theta_base", "has_theta_all",
    "in_year_stratum",
]


def race_hash(race_id: str) -> str:
    """The ordering key. SPEC_P0 4.3: sha256(race_id) ascending, take top k."""
    return hashlib.sha256(race_id.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# phase 1 — stratum variables
# --------------------------------------------------------------------------

def scm_rows(scm_html: str) -> list[list[str]]:
    """Rows of the Scm page's single table, as cell text.

    Provenance: pages["Scm"] holds one <table> whose caption is
    '출전번호별 단,연,복승식의 배당률, 매출총액, 취소마를 제공하는 표'
    (SPEC_P0 3.2(b)). Its shape, from the archive:

        row 0   title            ['제주 제3경주 2018년 05월 04일 (금)']
        row 1   pool header      ['단승식', '연승식', '출전 번호', '복승식']
        row 2   column header    ['1', '2', ... , '14']   <- always 1..14, fixed
        row 3.. one per horse    ['7.2', '1.4', '1', '1', '14.4', ...]
        row -2  sales totals     ['단승식 : 18,432,400원', ...]
        row -1  cancellation     ['취소마공지', '취소마가 없습니다.']
    """
    m = TABLE_RE.search(scm_html)
    if not m:
        return []
    return [[text(c) for c in TD_RE.findall(tr)] for tr in TR_RE.findall(m.group(0))]


def is_column_header(row: list[str]) -> bool:
    """The 1..14 header row, matched structurally rather than by position.

    This must be excluded before counting horses: its cell at index 2 is the
    digit '3', which would otherwise make it look like a data row.
    """
    return len(row) >= 4 and row == [str(i + 1) for i in range(len(row))]


def horse_rows(rows: list[list[str]]) -> list[list[str]]:
    """One row per REGISTERED horse.

    등록두수 is read here, from the KRA-served Scm HTML, and NOT from the
    collector's page-key count. SPEC_P0 IC-4b compares those two precisely
    because the page keys are generated from a field size N whose origin is
    absent from the archive (4.1, r2-K2, OPEN_ITEMS #2). Taking the stratum
    variable from the collector's side would make the sample inherit the very
    quantity the sample is meant to help check.

    A scratched horse keeps its row, with '----' in the 단승/연승 cells, so
    this counts registered rather than starting horses — which is what the
    '등록두수' stratum asks for.
    """
    out = []
    for r in rows:
        if len(r) >= 4 and not is_column_header(r) and r[2].isdigit():
            out.append(r)
    return out


def size_band(n: int) -> str:
    """SPEC_P0 4.3: 등록두수 ≤7 / 8–10 / ≥11. 착순 규칙 경계."""
    if n <= 7:
        return "le7"
    if n <= 10:
        return "8to10"
    return "ge11"


def cancel_notice_text(rows: list[list[str]]) -> str:
    """The 취소마공지 row's payload cell, verbatim.

    Provenance: last row of the Scm table. It names scratched horses, or reads
    '취소마가 없습니다.'. This row is not an odds cell, so reading it does not
    presuppose the '----' rule under test (the same non-circularity argument
    p0_probe.py makes for its cancel probe).
    """
    for r in reversed(rows):
        if r and r[0].startswith("취소마공지"):
            return r[1] if len(r) > 1 else ""
    return ""


def count_cancel_dashes(rows: list[list[str]]) -> int:
    """Cells that are a run of 3+ dashes, i.e. '----'. Single '-' is excluded:
    SPEC_P0 1.2 classifies it as a structural blank (lower triangle or beyond
    the field size), not a scratch."""
    return sum(1 for r in rows for c in r if DASH_RUN_RE.match(c))


def count_theta(pages: dict) -> tuple[int, int]:
    """(theta cells in Scm/Both/Bc, theta cells in every page).

    Provenance: a whole cell equal to '9999.9' in the page HTML. Counted by
    tag-boundary regex rather than by parsing tables, because 27 pages x 19,301
    races is the whole archive and presence is all the stratum needs.

    '_probe' is skipped. SPEC_P0 1 records it as byte-identical to page '1',
    so counting it would double every advanced-page cell.

    Two counts are kept because the spec's theta measurement (1.2) only covered
    Scm/Both/Bc. Which of the two defines the stratum is a decision recorded in
    sample_38.json, not one buried here.
    """
    base = adv = 0
    for key, page in pages.items():
        if isinstance(page, str):
            base += len(THETA_CELL_RE.findall(page))
        elif isinstance(page, dict):
            for variant, html_ in page.items():
                if variant == "_probe" or not isinstance(html_, str):
                    continue
                adv += len(THETA_CELL_RE.findall(html_))
    return base, base + adv


def build_strata(archive: pathlib.Path, out_csv: pathlib.Path) -> None:
    year_dirs = sorted(p for p in archive.glob("kra_*") if p.is_dir())
    if not year_dirs:
        sys.exit(f"no kra_* year directories under {archive}")

    rows_out: list[dict] = []
    bad: Counter[str] = Counter()

    for ydir in year_dirs:
        files = sorted(ydir.rglob("*.json.gz"))
        print(f"  {ydir.name}: {len(files)} races", file=sys.stderr)
        for f in files:
            try:
                d = json.loads(gzip.decompress(f.read_bytes()))
            except Exception as exc:  # noqa: BLE001 - report, do not mask
                bad["unreadable"] += 1
                print(f"    unreadable {f.name}: {exc}", file=sys.stderr)
                continue

            rid = d.get("race_id", "")
            m = RACE_ID_RE.match(rid)
            if not m:
                bad["bad race_id"] += 1
                print(f"    unparseable race_id {rid!r} in {f.name}", file=sys.stderr)
                continue
            year, _mm, _dd, meet, race_no = m.groups()

            pages = d.get("pages", {})
            scm = pages.get("Scm")
            if not isinstance(scm, str):
                bad["no Scm page"] += 1
                print(f"    no Scm page: {rid}", file=sys.stderr)
                continue

            rows = scm_rows(scm)
            horses = horse_rows(rows)
            nums = [int(r[2]) for r in horses]
            n_reg = len(horses)

            notice = cancel_notice_text(rows)
            n_dashes = count_cancel_dashes(rows)
            theta_base, theta_all = count_theta(pages)

            def n_keys(page_key: str) -> int:
                p = pages.get(page_key)
                return len([k for k in p if k != "_probe"]) if isinstance(p, dict) else -1

            rows_out.append({
                "race_id": rid,
                "year": int(year),
                "meet": int(meet),
                "race_no": int(race_no),
                "n_registered": n_reg,
                "size_band": size_band(n_reg),
                # 1..N consecutive? recorded, not assumed. A gap would mean the
                # horse-number column is not a dense field list.
                "horse_nums_consecutive": int(nums == list(range(1, n_reg + 1))),
                "n_keys_3bc": n_keys("3Bc"),
                "n_keys_3both": n_keys("3Both"),
                "cancel_notice": notice,
                # 취소마 있음: '----' printed in the Scm table. The stratum
                # exists for '----' 처리 (SPEC_P0 4.3), so the trigger is the
                # token itself. The notice text is kept alongside so the ~0.1%
                # disagreement SPEC_P0 1.2 reports stays visible.
                "has_cancel_dash": int(n_dashes > 0),
                "theta_cells_base": theta_base,
                "theta_cells_all": theta_all,
                "has_theta_base": int(theta_base > 0),
                "has_theta_all": int(theta_all > 0),
                "in_year_stratum": int(int(year) in YEARS),
            })

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows_out.sort(key=lambda r: r["race_id"])
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=STRATA_FIELDS)
        w.writeheader()
        w.writerows(rows_out)

    print(f"\nwrote {out_csv}  ({len(rows_out)} races)")
    if bad:
        print("skipped:")
        for k in sorted(bad):
            print(f"  {k}: {bad[k]}")


# --------------------------------------------------------------------------
# phase 2 — deterministic selection, reading strata.csv only
# --------------------------------------------------------------------------

def sha256_file(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pick(pool: list[dict], k: int, taken: set[str]) -> list[str]:
    """Top k by sha256(race_id) ascending, skipping already-selected races."""
    ordered = sorted((r for r in pool if r["race_id"] not in taken),
                     key=lambda r: race_hash(r["race_id"]))
    return [r["race_id"] for r in ordered[:k]]


def build_sample(strata_csv: pathlib.Path, out_json: pathlib.Path,
                 theta_col: str) -> int:
    with strata_csv.open(encoding="utf-8") as fh:
        allrows = list(csv.DictReader(fh))
    if not allrows:
        sys.exit(f"{strata_csv} is empty; run --phase strata first")

    # The frame is the four year strata of the 4.3 table. Races from 2017,
    # 2019, 2023 and 2024 belong to no year stratum and so cannot be drawn.
    frame = [r for r in allrows if r["in_year_stratum"] == "1"]

    cells: dict[tuple, list[dict]] = defaultdict(list)
    for r in frame:
        cells[(int(r["meet"]), int(r["year"]), r["size_band"])].append(r)

    full_cross = [(m, y, b) for m in MEETS for y in YEARS for b in SIZE_BANDS]
    empty = [c for c in full_cross if not cells.get(c)]
    filled = [c for c in full_cross if cells.get(c)]

    # ---------------------------------------------------------- quota rule
    # Researcher's ruling, 2026-08-11: the sample size FOLLOWS the design; the
    # design does not follow the sample size.
    #
    #   cross cells that exist  x PER_CELL      = 34 x 1 = 34
    #   coverage strata         x PER_COVERAGE  =  2 x 2 =  4
    #                                                      ----
    #                                                        38
    #
    # Two of the 36 cross cells are empty: Seoul and Busan ran no race with 7
    # or fewer registered horses in 2025. An empty cell yields nothing, so 36
    # cells become 34 and the sample is 38 rather than 40.
    #
    # Explicitly REJECTED (would each be the post-hoc freedom r2-K3 warns about):
    #   - handing the empty cells' quota to other cells to keep 40
    #   - dropping the year stratum
    #   - moving the 등록두수 boundary so the cells fill
    # The bands exist for the test's sake (<=7 is where the place-payout rule
    # changes), so bending them to suit the data inverts the design.
    #
    # The 2/2 split of the coverage quota remains the one thing SPEC_P0 4.3
    # does not fix; it is flagged in the output rather than presented as
    # arithmetic.
    per_cell = 1
    per_coverage = 2

    coverage_pool = {
        "cancel": [r for r in frame if r["has_cancel_dash"] == "1"],
        "theta": [r for r in frame if r[theta_col] == "1"],
    }

    sample_n = len(filled) * per_cell + len(COVERAGE) * per_coverage

    # -------------------------------------------------- stop-and-report gates
    # Empty cells are no longer a stop condition — the ruling above absorbs
    # them. What still stops the run is a stratum that cannot fill a quota it
    # was allocated, because that would silently shrink the sample.
    problems = []
    for name in COVERAGE:
        if len(coverage_pool[name]) < per_coverage:
            problems.append(
                f"커버리지 층 '{name}'의 모집단이 {len(coverage_pool[name])}경주로 "
                f"정원 {per_coverage}을 채울 수 없다.")
    if not filled:
        problems.append("교차 층이 전부 비어 있다.")

    if problems:
        print("\n중단: 층 설계와 정원이 맞지 않는다.\n")
        for p in problems:
            print(f"  - {p}")
        print("\n관측된 층 분포 (meet x year x 등록두수):")
        for c in full_cross:
            print(f"  meet{c[0]} / {c[1]} / {c[2]:<5} : {len(cells.get(c, []))}")
        print("\n표본 크기는 비평 답변(r2-K7)의 근거이므로 임의로 조정하지 않는다.")
        return 1

    # ------------------------------------------------------------- allocation
    taken: set[str] = set()
    allocation = []

    # Empty cells are carried in the allocation with quota 0 rather than
    # dropped, so that "why 34 cells and not 36" is answerable from this file
    # alone, without re-reading strata.csv.
    for c in full_cross:
        available = cells.get(c, [])
        quota = per_cell if available else 0
        chosen = pick(available, quota, taken)
        taken.update(chosen)
        allocation.append({
            "stratum": {"meet": c[0], "year": c[1], "size_band": c[2]},
            "kind": "cross",
            "n_available": len(available),
            "quota": quota,
            "selected": chosen,
            **({"empty": True,
                "note": "이 층에 해당하는 경주가 아카이브에 없다. 정원 0."}
               if not available else {}),
        })

    for name in COVERAGE:
        chosen = pick(coverage_pool[name], per_coverage, taken)
        taken.update(chosen)
        allocation.append({
            "stratum": {"coverage": name},
            "kind": "coverage",
            "n_available": len(coverage_pool[name]),
            "quota": per_coverage,
            "selected": chosen,
        })

    sample = sorted(taken, key=race_hash)
    if len(sample) != sample_n:
        print(f"\n중단: 배분 결과가 {len(sample)}경주로 계산된 정원 "
              f"{sample_n}과 다르다.")
        return 1

    by_id = {r["race_id"]: r for r in allrows}
    transcript = sample[:TRANSCRIPT_N]

    out = {
        "spec": "SPEC_P0 4.3 (r2-K7, 2026-08-11 표본 크기 판정)",
        "purpose": "재수집 실행 전에 고정하는 바이트 대조 표본과 독립 전사 표본",
        "source": {
            "strata_csv": strata_csv.as_posix(),
            "strata_csv_sha256": sha256_file(strata_csv),
            "n_races_in_archive": len(allrows),
            "n_races_in_frame": len(frame),
        },
        "selection_rule": {
            "ordering": "sha256(race_id.encode('utf-8')) hex, ascending",
            "determinism": "난수 종자 없음, 시각 없음, 사람의 선택 없음",
            "frame": f"연도 층 {YEARS}에 속한 경주만. 그 외 연도는 어느 연도 층에도 없다",
            "theta_column": theta_col,
        },
        "quota_rule": {
            "sample_size": sample_n,
            "sample_size_is_derived": (
                "표본 크기는 층 설계에서 나온다. 40을 맞추려고 층을 바꾸지 않는다."
            ),
            "cross": {
                "factors": ["meet(3)", "year(4)", "size_band(3)"],
                "n_cells_designed": len(full_cross),
                "n_cells_empty": len(empty),
                "n_cells_filled": len(filled),
                "per_cell": per_cell,
                "subtotal": len(filled) * per_cell,
            },
            "empty_cells": [
                {"meet": m, "year": y, "size_band": b, "quota": 0,
                 "reason": "아카이브에 해당 경주가 0건"}
                for m, y, b in empty
            ],
            "coverage": {
                "strata": COVERAGE,
                "per_stratum": per_coverage,
                "subtotal": len(COVERAGE) * per_coverage,
            },
            "rejected_alternatives": [
                "빈 층 몫을 다른 층에 배분해 40을 유지",
                "연도 층을 제거",
                "등록두수 경계를 옮겨 빈 층을 채움",
            ],
            "rejected_because": (
                "층은 검사 목적에 맞춰 정한 것이다(≤7은 착순 규칙이 갈리는 경계). "
                "데이터 사정으로 층을 바꾸면 r2-K3이 지적한 사후 자유도가 된다. "
                "빈 층은 데이터의 사실이므로 그대로 둔다."
            ),
            "not_fixed_by_spec": (
                "SPEC_P0 4.3은 층 목록을 고정하지만, 커버리지 층 둘에 2/2로 "
                "나누는 것까지는 적지 않는다. 이 분할은 이 파일의 결정이며 "
                "연구자 판단 대상이다."
            ),
        },
        "zero_mismatch_upper_bound_95": {
            "value": round(1 - 0.05 ** (1 / sample_n), 4),
            "percent": f"{(1 - 0.05 ** (1 / sample_n)) * 100:.2f}%",
            "rule": "1 - 0.05^(1/n), 이항 단측 95% 상한, 불일치 0건일 때",
            "meaning": (
                f"이 표본에서 불일치 0건이 나와도 말할 수 있는 것은 "
                f"불일치율이 약 {(1 - 0.05 ** (1 / sample_n)) * 100:.1f}% "
                f"미만이라는 것뿐이다. 그 이상을 주장하지 않는다."
            ),
        },
        "allocation": allocation,
        "sample": [
            {
                "race_id": rid,
                "sha256": race_hash(rid),
                "year": int(by_id[rid]["year"]),
                "meet": int(by_id[rid]["meet"]),
                "n_registered": int(by_id[rid]["n_registered"]),
                "size_band": by_id[rid]["size_band"],
                "has_cancel_dash": int(by_id[rid]["has_cancel_dash"]),
                "has_theta_all": int(by_id[rid]["has_theta_all"]),
                "has_theta_base": int(by_id[rid]["has_theta_base"]),
            }
            for rid in sample
        ],
        "transcript_5": transcript,
        "transcript_rule": (
            "같은 해시 순서의 상위 5개. 바이트 대조 결과를 보기 전에 정한다 "
            "(SPEC_P0 4.3)."
        ),
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\nwrote {out_json}  ({len(sample)} races, {len(transcript)} for transcription)")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=pathlib.Path,
                    help="raw_collected_v3_15w. read-only. required for --phase strata")
    ap.add_argument("--phase", choices=["strata", "sample", "all"], default="all")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("outputs/p0"))
    # Default is the base-page measurement. Measured on the full archive,
    # theta appears somewhere in 82.7% of races once 3Bc/3Both are counted, so
    # 'has_theta_all' does not stratify anything. The base pages give 583 races
    # (3.0%), and they are also the only pages SPEC_P0 1.2 actually measured.
    ap.add_argument("--theta-column", default="has_theta_base",
                    choices=["has_theta_all", "has_theta_base"],
                    help="which theta measurement defines the 'θ 인쇄 있음' stratum")
    args = ap.parse_args()

    strata_csv = args.out / "strata.csv"
    sample_json = args.out / "sample_38.json"

    if args.phase in ("strata", "all"):
        if args.archive is None or not args.archive.is_dir():
            sys.exit(f"no such archive: {args.archive}")
        print("scanning archive", file=sys.stderr)
        build_strata(args.archive, strata_csv)

    if args.phase in ("sample", "all"):
        if not strata_csv.exists():
            sys.exit(f"{strata_csv} missing; run --phase strata first")
        sys.exit(build_sample(strata_csv, sample_json, args.theta_column))


if __name__ == "__main__":
    main()
