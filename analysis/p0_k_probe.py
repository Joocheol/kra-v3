#!/usr/bin/env python3
"""P0-K: 격자 식별의 재료가 원자료에 있는지 확인한다.

    python3 analysis/p0_k_probe.py --archive ~/Dropbox/.../raw_collected_v3_15w

배당률은 O = A / (100·n) 이다.  A = (1-t)·S / m 이고 n 은 그 조합에 걸린
100원 단위마권 수(정수)다.  풀별 발매금액 S 를 알면 O 의 후보가 유한 격자로
확정되므로, 우측 절단(9999.9)된 셀도 가정 없이 경계가 잡힌다.  이 프로브는
그 계산에 들어가는 재료 -- S, 출주두수, 그리고 S 의 회계 정의 -- 만 확인한다.
복원은 하지 않는다.

  A. 발매금액    <tfoot> 의 라벨과 값.  풀별로 분리되어 있는가, 단위는 원인가,
                 100 으로 나누어떨어지는가.

  B. 출주두수    등록/취소/출주 두수와 도착마번.  연승식의 분모 m(2 또는 3)이
                 등록두수로 정해지는지 출주두수로 정해지는지 가려낸다.

  C. S 의 정의   각 셀의 n 이 존재할 수 있는 정수 구간을 구한다.  구간이 비면
                 (S, t, m) 중 하나가 틀린 것이다.  취소마가 있는 경주에서만
                 빈 구간이 쏟아지면 S 가 반환분을 포함한 금액이라는 뜻이다.

산술.  경계가 부동소수점 오차에 밀리면 판정 전체가 무의미해지므로 전부 정수
연산으로 한다.  (1-t) 는 8/10 또는 73/100 의 유리수로, 표시 배당률 O 는
d = 10·O 의 정수로 다룬다.  환급금 R = A/n, 표시 배당률 = R/100 이므로

    반올림(시행령 제11조)  R ∈ [10d-5, 10d+5)   n ∈ ( pS/(qm(10d+5)), pS/(qm(10d-5)) ]
    버림                   R ∈ [10d,   10d+10)  n ∈ ( pS/(qm(10d+10)), pS/(qm·10d)   ]
    규칙 무관(합집합)      R ∈ [10d-5, 10d+10)  n ∈ ( pS/(qm(10d+10)), pS/(qm(10d-5)) ]

규칙 무관 구간이 정수 하나만 담으면 n 은 규칙과 무관하게 확정된다.  그 n 으로
R 을 되짚어 표시값 d 를 어느 규칙이 재현하는지 보면 반올림 규칙이 판정된다.

무엇이 무엇을 잡아내는지는 합성자료로 확인했다.  '빈 구간' 비율은 S 가 0.1%만
틀려도 경주의 97%에서 걸리고 참 가설에서는 한 건도 나오지 않는다.  반면 Σn
구간과 S/100 의 대조는 저배당 셀의 구간 폭에 묻혀 S 가 5% 틀려도 대부분
'일치'로 나온다 -- 참고용으로만 싣는다.

표준 라이브러리만 쓴다.  아카이브는 읽기 전용으로만 연다.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import gzip
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from kra.archive import months                      # noqa: E402
from kra.race import parse_race                     # noqa: E402

HORSE_COL_HEADER = "출전 번호"
ODDS = re.compile(r"^\d+(?:\.\d)?$")
AMOUNT = re.compile(r"[\d,]{2,}")
CAP_D = 99999          # 9999.9, 우측 절단
FLOOR_D = 10           # 1.0,    좌측 절단(원금보전).  참값인지 보전값인지 구별 불가

POOLS = {
    "단승식":   {"page": "Scm",  "p": 8,  "q": 10,  "m": 1},
    "연승식":   {"page": "Scm",  "p": 8,  "q": 10,  "m": None},   # 2 또는 3, C에서 판정
    "복승식":   {"page": "Scm",  "p": 73, "q": 100, "m": 1},
    "쌍승식":   {"page": "Both", "p": 73, "q": 100, "m": 1},
    "복연승식": {"page": "Bc",   "p": 73, "q": 100, "m": 3},
}
# 삼복승·삼쌍승은 고정마별로 페이지가 나뉘어 같은 조합이 여러 번 나온다.
# 중복 제거 규칙 자체가 별도 검증거리이므로 C 에서는 제외하고 A 만 본다.
CHECKED_POOLS = ("단승식", "연승식", "복승식", "쌍승식", "복연승식")
PLACE_M = (2, 3)
POOL_NAMES = ("삼복승식", "삼쌍승식", "복연승식", "복승식", "쌍승식", "연승식", "단승식")


# --------------------------------------------------------------------- 경계

def bounds(p, q, m, S, d, rule):
    """d = 10·O 에 대응하는 n 의 정수 구간 [lo, hi].  lo > hi 이면 불가능."""
    num, base = p * S, q * m
    if d == CAP_D:
        # 표시 상한이므로 위쪽이 열려 있다.  R >= 10d-5 (반올림) 또는 >= 10d
        # (버림) 이라는 단측 정보만 남고, n 의 하한은 1 이다.  여기에 양측
        # 공식을 쓰면 참값이 구간 아래로 빠져나가 멀쩡한 경주가 불가능으로
        # 찍힌다.
        return 1, num // (base * (10 * d if rule == "floor" else 10 * d - 5))
    if rule == "round":
        return num // (base * (10 * d + 5)) + 1, num // (base * (10 * d - 5))
    if rule == "floor":
        return num // (base * (10 * d + 10)) + 1, num // (base * 10 * d)
    return num // (base * (10 * d + 10)) + 1, num // (base * (10 * d - 5))


def reproduces(p, q, m, S, n, d):
    """n 이 확정됐을 때 표시값 d 를 어느 규칙이 재현하는가."""
    num, base = p * S, q * m                          # R = num / (base·n)
    # round: 10d-5 <= R < 10d+5   /  floor: 10d <= R < 10d+10
    lo_r, hi_r = base * n * (10 * d - 5), base * n * (10 * d + 5)
    lo_f, hi_f = base * n * 10 * d, base * n * (10 * d + 10)
    return (lo_r <= num < hi_r), (lo_f <= num < hi_f)


# --------------------------------------------------------------------- 수집

def sales_from_foot(cells):
    out = {}
    for c in cells:
        if ":" in c.cell_raw:
            label, _, amount = c.cell_raw.partition(":")
            out[label.strip()] = amount.strip()
    return out


def amount_to_won(text):
    m = AMOUNT.search(text or "")
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def match_pool(label):
    flat = (label or "").replace(" ", "")
    for name in POOL_NAMES:                           # 긴 이름부터: 복승식 ⊄ 삼복승식
        if name in flat:
            return name
    return None


def page_cells(rows):
    g = collections.defaultdict(lambda: ([], []))
    for r in rows:
        if r.spanned:
            continue
        body, foot = g[(r.page_key, r.page_variant)]
        (foot if r.section == "foot" else body).append(r)
    out = {}
    for key, (body, foot) in g.items():
        hcol = next((r.col for r in body if r.col_header == HORSE_COL_HEADER), None)
        out[key] = (body, foot, hcol)
    return out


def assess(pool, ds, S, m):
    """한 풀의 셀 목록 ds 에 대한 판정.  ds 는 d = 10·O 의 정수 목록."""
    p, q = POOLS[pool]["p"], POOLS[pool]["q"]
    live = [d for d in ds if d != FLOOR_D]            # 1.0 은 좌측 절단, 경계가 무의미
    bad_round = bad_floor = 0
    point = rule_round = rule_floor = rule_both = rule_neither = 0
    lo_sum = hi_sum = 0
    for d in live:
        lo, hi = bounds(p, q, m, S, d, "round")
        if lo > hi:
            bad_round += 1
        else:
            lo_sum += lo
            hi_sum += hi
        flo, fhi = bounds(p, q, m, S, d, "floor")
        if flo > fhi:
            bad_floor += 1
        if d == CAP_D:                                # 절단 셀은 규칙 판정 대상 아님
            continue
        alo, ahi = bounds(p, q, m, S, d, "agnostic")
        if alo == ahi:
            point += 1
            r_ok, f_ok = reproduces(p, q, m, S, alo, d)
            if r_ok and f_ok:
                rule_both += 1
            elif r_ok:
                rule_round += 1
            elif f_ok:
                rule_floor += 1
            else:
                rule_neither += 1
    target = S // 100
    if S % 100:
        verdict = "S가 100의 배수가 아님"
    elif bad_round:
        verdict = "빈 구간"
    elif any(d == FLOOR_D for d in ds):
        verdict = "1.0 있어 보류"
    elif target < lo_sum:
        verdict = "S가 작음"
    elif target > hi_sum:
        verdict = "S가 큼"
    else:
        verdict = "일치"
    return {
        "n_live": len(live), "bad_round": bad_round, "bad_floor": bad_floor,
        "point": point, "rule_round": rule_round, "rule_floor": rule_floor,
        "rule_both": rule_both, "rule_neither": rule_neither,
        "sum_lo": lo_sum, "sum_hi": hi_sum, "target": target, "verdict": verdict,
    }


def probe_race(payload):
    race, rows = parse_race(payload, sections=("body", "foot"))
    pages = page_cells(rows)
    rec = {
        "race_id": race.race_id, "date": race.date, "meet": race.meet,
        "n_registered": race.n_registered, "n_scratched": len(race.scratched),
        "n_starters": race.n_registered - len(race.scratched),
        "n_arrival": len(race.arrival), "problems": race.problems,
        "sales": {}, "col_groups": {}, "tokens": collections.Counter(), "pools": {},
    }

    for (pk, variant), (_, foot, _) in sorted(pages.items()):
        if variant:                                   # 고정마 페이지는 대표만
            continue
        s = sales_from_foot(foot)
        if s:
            rec["sales"][pk] = s

    per_pool = collections.defaultdict(list)
    for (pk, variant), (body, _, hcol) in sorted(pages.items()):
        if variant:
            continue
        rec["col_groups"].setdefault(
            pk, sorted({r.col_group for r in body if r.col != hcol and r.col_group}))
        for r in body:
            if hcol is not None and r.col == hcol:
                continue
            if not ODDS.match(r.cell_raw):
                rec["tokens"][r.cell_raw] += 1
                continue
            pool = (r.col_group if r.col_group in POOLS else None) if pk == "Scm" \
                else next((k for k, v in POOLS.items() if v["page"] == pk), None)
            if pool is None:
                rec["tokens"][f"<그룹?{pk}:{r.col_group}>"] += 1
                continue
            per_pool[pool].append(round(float(r.cell_raw) * 10))

    amounts = {}
    for s in rec["sales"].values():
        for label, raw in s.items():
            pool = match_pool(label)
            if pool:
                amounts[pool] = amount_to_won(raw)

    for pool in CHECKED_POOLS:
        ds = per_pool.get(pool)
        if not ds:
            continue
        S = amounts.get(pool)
        info = {"n_cells": len(ds), "S": S,
                "n_censored": sum(1 for d in ds if d == CAP_D),
                "n_floored": sum(1 for d in ds if d == FLOOR_D)}
        if S:
            ms = PLACE_M if POOLS[pool]["m"] is None else (POOLS[pool]["m"],)
            info["fits"] = {f"m{m}": assess(pool, ds, S, m) for m in ms}
        rec["pools"][pool] = info

    rec["tokens"] = dict(rec["tokens"])
    return rec


# --------------------------------------------------------------------- 집계

def run_month(month, keep):
    recs, ex, errs = [], [], []
    for path in month.files:
        try:
            payload = json.loads(gzip.decompress(path.read_bytes()))
        except Exception as exc:                      # noqa: BLE001
            errs.append({"file": path.name, "error": f"읽기: {exc}"})
            continue
        try:
            rec = probe_race(payload)
        except Exception as exc:                      # noqa: BLE001
            errs.append({"file": path.name, "error": f"파싱: {exc}"})
            continue
        if len(ex) < keep:
            ex.append(rec)
        recs.append(rec)
    return {"month": month.key, "records": recs, "examples": ex, "errors": errs}


def summarise(recs):
    labels, sample = collections.Counter(), {}
    mods = collections.defaultdict(collections.Counter)
    groups = collections.defaultdict(collections.Counter)
    tokens = collections.Counter()
    field = collections.Counter()
    arr_bad = 0
    feas = collections.defaultdict(lambda: collections.Counter())
    rules = collections.defaultdict(collections.Counter)
    sums = collections.defaultdict(collections.Counter)
    place = collections.defaultdict(collections.Counter)
    no_S = collections.Counter()

    for r in recs:
        for pk, s in r["sales"].items():
            for label, raw in s.items():
                k = f"{pk} :: {label}"
                labels[k] += 1
                sample.setdefault(k, raw)
                won = amount_to_won(raw)
                mods[k]["파싱실패" if won is None else
                       f"%100=={won % 100}"] += 1
        for pk, gs in r["col_groups"].items():
            groups[pk].update(gs)
        tokens.update(r["tokens"])
        field[(r["n_registered"], r["n_scratched"])] += 1
        if r["n_arrival"] > r["n_starters"] > 0:
            arr_bad += 1

        scr = "취소有" if r["n_scratched"] else "취소無"
        for pool, info in r["pools"].items():
            if not info.get("fits"):
                no_S[pool] += 1
                continue
            for tag, f in info["fits"].items():
                key = (pool, tag, scr)
                feas[key]["빈구간有" if f["bad_round"] else "빈구간無"] += 1
                feas[key]["_cells"] += f["n_live"]
                feas[key]["_bad"] += f["bad_round"]
                sums[key][f["verdict"]] += 1
                rules[pool]["점식별"] += f["point"]
                rules[pool]["반올림만"] += f["rule_round"]
                rules[pool]["버림만"] += f["rule_floor"]
                rules[pool]["둘다"] += f["rule_both"]
                rules[pool]["둘다아님"] += f["rule_neither"]
            if pool == "연승식":
                # 연승식은 셀이 출주두수만큼(<=16)뿐이라 빈 구간이 잘 생기지
                # 않는다.  대신 m 을 2 로 잘못 잡으면 모든 n 이 1.5 배로 어긋나
                # Σn 이 S/100 에서 50% 벗어나므로, 여기서는 Σn 이 기준이다.
                ok = sorted(t for t, f in info["fits"].items()
                            if f["verdict"] == "일치")
                place[(r["n_starters"], r["n_registered"])][
                    ",".join(ok) or "없음"] += 1
    return {
        "n_races": len(recs), "sales_labels": labels.most_common(),
        "sales_sample": sample,
        "sales_mod": {k: v.most_common(4) for k, v in mods.items()},
        "col_groups": {k: v.most_common() for k, v in groups.items()},
        "tokens": tokens.most_common(30),
        "field": sorted((a, b, n) for (a, b), n in field.items()),
        "arrival_mismatch": arr_bad, "no_S": no_S.most_common(),
        "feasibility": {" | ".join(k): dict(v) for k, v in feas.items()},
        "rules": {k: dict(v) for k, v in rules.items()},
        "sums": {" | ".join(k): v.most_common() for k, v in sums.items()},
        "place_m": {f"출주{a}두/등록{b}두": v.most_common()
                    for (a, b), v in sorted(place.items())},
    }


def report(s, out):
    w = print
    w(f"\n{'=' * 74}\nP0-K 프로브 — {s['n_races']:,} 경주\n{'=' * 74}")

    w("\n[A] 발매금액 필드")
    if not s["sales_labels"]:
        w("  없음. <tfoot> 에서 'label : amount' 를 찾지 못했다. C 는 전부 무효.")
    for k, n in s["sales_labels"]:
        raw = s["sales_sample"][k]
        w(f"  {k:<32} {n:>7,}회  예 {raw!r:<16} [{match_pool(k) or '미매칭'}]")
        w("      100 나머지: " + ", ".join(f"{a}({b:,})" for a, b in s["sales_mod"][k]))
    if s["no_S"]:
        w("  S 를 못 찾아 C 를 건너뛴 풀: " +
          ", ".join(f"{a}({b:,})" for a, b in s["no_S"]))

    w("\n[A-2] 페이지별 col_group — 승식 열 분해가 유효한지")
    for pk, gs in sorted(s["col_groups"].items()):
        w(f"  {pk:<8} " + ", ".join(f"{g}({n:,})" for g, n in gs))

    w("\n[A-3] 배당률로 파싱되지 않은 셀")
    for tok, n in s["tokens"]:
        w(f"  {tok!r:<26} {n:>12,}")

    w("\n[B] 등록두수 / 취소두수 (취소 있는 경우만)")
    for reg, scr, n in s["field"]:
        if scr:
            w(f"  등록 {reg:>2} 취소 {scr:>2} -> 출주 {reg - scr:>2}   {n:>7,}")
    w(f"  도착마번이 출주두수를 넘는 경주: {s['arrival_mismatch']:,}")

    w("\n[B-2] 연승식 m — Σn 이 맞아떨어지는 m 을 출주/등록 두수와 교차")
    for k, rows in s["place_m"].items():
        w(f"  {k:<20} " + ", ".join(f"{t}({n:,})" for t, n in rows))

    w("\n[C] 빈 구간 — S 정의의 결정적 검정 (승식 | m | 취소)")
    w(f"  {'':<34}{'경주':>9}{'빈구간有':>10}{'셀':>12}{'불가능셀':>11}")
    for k, v in sorted(s["feasibility"].items()):
        races = v.get("빈구간有", 0) + v.get("빈구간無", 0)
        w(f"  {k:<34}{races:>9,}{v.get('빈구간有', 0):>10,}"
          f"{v.get('_cells', 0):>12,}{v.get('_bad', 0):>11,}")

    w("\n[C-2] 반올림 규칙 — 규칙무관 점식별 셀에서 표시값 재현")
    for pool, v in sorted(s["rules"].items()):
        pt = v.get("점식별", 0)
        if not pt:
            continue
        w(f"  {pool:<10} 점식별 {pt:>10,}  " + ", ".join(
            f"{a}={v.get(a, 0):,}" for a in ("반올림만", "버림만", "둘다", "둘다아님")))

    w("\n[C-3] Σn 대조 (참고용 — 저배당 셀 구간 폭에 묻혀 검출력이 낮다)")
    for k, rows in sorted(s["sums"].items()):
        w(f"  {k:<34} " + ", ".join(f"{a}={b:,}" for a, b in rows))

    w(f"\n전체 결과: {out}\n")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True, type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("outputs/p0_k_probe.json"))
    ap.add_argument("--year", type=int)
    ap.add_argument("--limit", type=int, metavar="N", help="월별 최대 N 경주")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--examples", type=int, default=2)
    args = ap.parse_args()

    if not args.archive.is_dir():
        sys.exit(f"아카이브 없음: {args.archive}")
    work = months(args.archive, year=args.year, limit=args.limit)
    if not work:
        sys.exit("읽을 것이 없다")
    total = sum(len(m.files) for m in work)
    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"{total:,} 경주, {len(work)} 개월, 워커 {workers}", file=sys.stderr)

    t0 = time.time()
    recs, ex, errs, done = [], [], [], 0
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(run_month, m, args.examples): m for m in work}
        for fut in cf.as_completed(futs):
            m = futs[fut]
            try:
                res = fut.result()
            except Exception as exc:                  # noqa: BLE001
                errs.append({"month": m.key, "error": str(exc)})
                print(f"  {m.key}: 실패 {exc}", file=sys.stderr)
                continue
            recs.extend(res["records"])
            ex.extend(res["examples"])
            errs.extend(res["errors"])
            done += 1
            print(f"  [{done}/{len(work)}] {res['month']}: {len(res['records'])} 경주",
                  file=sys.stderr)

    s = summarise(recs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"archive": str(args.archive), "n_races": len(recs),
         "elapsed_seconds": round(time.time() - t0, 1),
         "summary": s, "examples": ex, "errors": errs},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report(s, args.out)
    if errs:
        print(f"오류 {len(errs):,}건은 결과 파일에 있다.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
