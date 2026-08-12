#!/usr/bin/env python3
"""P0-S: 발매금액이 없는 풀의 S 를 격자 제약으로 복원할 수 있는지 표본으로 판정한다.

    python3 analysis/p0_s_recover.py --archive ~/Dropbox/.../raw_collected_v3_15w \
        --sample 200

배경.  <tfoot> 의 발매금액은 Scm 페이지에만 있고 단승·연승·복승·총매출액뿐이다.
쌍승식과 복연승식에는 S 가 없어 P0-K 의 격자 판정을 걸 수 없었다.  P2 아이디어의
표적이 쌍승식 절단 배당이므로, S 를 배당률 표에서 되찾을 수 있는지가 선결 문제다.

원리.  배당률은 R = X/(base·n), X = 100·p·s, S = 100·s, base = q·m 이고 n 은
정수다.  표시값 d = 10·O 에 대해 반올림 규칙이면

    X ∈ [ n·base·(10d-5),  n·base·(10d+5) )

이므로 "X 가 셀 d 와 양립한다" 는 정수 n>=1 의 존재로 환원되고, 판정은 나눗셈
두 번이다:  X//LO > X//HI.  S 를 미지수로 두고 모든 셀을 통과하는 X 를 찾는다.

식별의 구조 -- 합성자료로 확인한 세 가지.

  (1) 셀 j 가 정보를 주는 조건은 n_j < d_j, 즉 d_j > sqrt(X/(10·base)) 다.
      배당률이 낮은 셀은 격자 간격이 구간 폭보다 좁아 아무것도 배제하지 못한다.
      쌍승식은 조합이 100~250 개라 긴 배당이 풍부해 유효 셀이 수십 개 나온다.

  (2) 문제에는 곱셈 대칭이 있다.  X 가 해이면 n_j -> k·n_j 로 kX 도 정확히
      해다.  따라서 S 는 양의 정수배를 빼고만 식별된다.  참값이 최소해의 k 배
      이려면 모든 조합의 마권 수가 k 의 배수여야 하는데, 합성 180 회에서
      gcd(n_j) 는 예외 없이 1 이었다.  그러므로 참값 = 최소해다.

  (3) Σ_j n_j = s (패리뮤추얼 항등식) 는 이 대칭을 그대로 보존하므로 후보를
      단 하나도 걸러내지 못한다.  P0-K 가 Σn 대조의 검출력이 낮다고 본 것과
      같은 사실의 다른 얼굴이다.  여기서는 아예 쓰지 않는다.

무엇이 이 스크립트를 반증하는가.  복승식은 S 가 <tfoot> 에 있다.  그 S 를
가리고 똑같이 복원한 뒤 참값과 맞춰 본다.  복승식에서 최소해가 참값을 재현하지
못하면 쌍승식 복원도 믿을 수 없다.  단승식은 셀이 출주두수만큼뿐이라 유효 셀이
거의 없어 실패가 예상되는데, 그 실패도 같은 조건식이 예측하는 바다 -- 방법이
어디서 서고 어디서 무너지는지를 함께 보기 위해 넣는다.

상한.  총매출액 - (단승+연승+복승) = 쌍승+복연승+삼복승+삼쌍승 이므로 이 잔여액이
쌍승식 S 의 엄격한 상한이다.  검증용 풀에도 같은 형태의 상한을 준다(복승식이면
총매출액 - 단승 - 연승).  가려진 풀만 미지로 두는 것이므로 유리한 정보를 넣지
않는다.

표준 라이브러리만 쓴다.  전부 정수 연산이다.  아카이브는 읽기 전용으로만 연다.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import gzip
import json
import math
import os
import pathlib
import random
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
FLOOR_D = 10           # 1.0,    최저배당 보전.  격자에서 벗어나므로 제외한다
TOTAL = "총매출"

POOLS = {
    "단승식":   {"page": "Scm",  "p": 8,  "q": 10,  "m": 1},
    "연승식":   {"page": "Scm",  "p": 8,  "q": 10,  "m": None},
    "복승식":   {"page": "Scm",  "p": 73, "q": 100, "m": 1},
    "쌍승식":   {"page": "Both", "p": 73, "q": 100, "m": 1},
    "복연승식": {"page": "Bc",   "p": 73, "q": 100, "m": 3},
}
POOL_NAMES = ("삼복승식", "삼쌍승식", "복연승식", "복승식", "쌍승식", "연승식", "단승식")

# 복원 대상.  KNOWN 은 S 가 <tfoot> 에 있어 참값 대조가 되는 검증용 풀이고,
# UNKNOWN 은 S 가 없어 실제로 복원해야 하는 표적이다.
KNOWN = ("복승식", "단승식")
UNKNOWN = ("쌍승식", "복연승식")


# --------------------------------------------------------------------- 격자

def lo_hi(d, base):
    """표시값 d 와 양립하는 X 의 구간 계수.  X ∈ [n·LO, n·HI)."""
    return base * (10 * d - 5), base * (10 * d + 5)


def predict_cost(LO1, HI1, x_min, x_max, c):
    """최고배당 셀만으로 생성될 후보 s 의 개수.  실행 전에 예산을 건다.

    이 값이 크다는 것은 최고배당이 낮다는 뜻이고, 그것은 곧 유효 셀이 없어
    복원이 실패한다는 뜻이기도 하다.  예산 초과는 공학적 사고가 아니라
    식별 실패의 신호로 읽어야 한다.
    """
    if x_max < LO1:
        return 0
    n_max, n_min = x_max // LO1, max(1, x_min // HI1)
    if n_max < n_min:
        return 0
    k = n_max - n_min + 1
    return int(k * (n_min + n_max) / 2 * (HI1 - LO1) / c) + k


def recover(ds, p, q, m, x_max, budget):
    """ds(=10·O 의 목록) 와 양립하는 s = S/100 을 전부 찾는다."""
    c, base = 100 * p, q * m
    live = sorted((d for d in ds if d not in (FLOOR_D, CAP_D)), reverse=True)
    n_cap = sum(1 for d in ds if d == CAP_D)
    n_floor = sum(1 for d in ds if d == FLOOR_D)
    if not live:
        return {"status": "판정불가", "reason": "격자에 걸리는 셀이 없다"}

    x_min = c * len(ds)                       # n_j >= 1 이므로 s >= 셀 수
    if n_cap:                                 # 절단 셀은 단측 하한을 준다
        x_min = max(x_min, lo_hi(CAP_D, base)[0])
    if x_max < x_min:
        return {"status": "판정불가", "reason": "상한이 하한보다 작다"}

    bounds = [lo_hi(d, base) for d in live]
    LO1, HI1 = bounds[0]
    rest = bounds[1:]
    cost = predict_cost(LO1, HI1, x_min, x_max, c)
    if cost > budget:
        return {"status": "예산초과", "predicted": cost, "d_top": live[0],
                "n_live": len(live), "n_cap": n_cap, "n_floor": n_floor}

    surv, tested = [], 0
    for n in range(max(1, x_min // HI1), x_max // LO1 + 1):
        a, b = max(n * LO1, x_min), min(n * HI1, x_max + 1)
        if a >= b:
            continue
        for s in range(-(-a // c), (b - 1) // c + 1):
            X = c * s
            tested += 1
            for LO, HI in rest:
                if X // LO <= X // HI:
                    break
            else:
                surv.append(s)

    if not surv:
        return {"status": "해없음", "tested": tested, "d_top": live[0],
                "n_live": len(live), "n_cap": n_cap, "n_floor": n_floor}

    lo = min(surv)
    # 곱셈 대칭 때문에 생존 집합은 최소해의 배수 둘레에 뭉친다.  최소해와
    # 같은 덩어리(1% 이내)만 떼어 내면 그것이 S 의 식별 구간이다.
    core = [x for x in surv if x <= lo * 1.01]
    mult = sorted({round(x / lo) for x in surv})
    return {"status": "복원", "tested": tested, "d_top": live[0],
            "n_live": len(live), "n_cap": n_cap, "n_floor": n_floor,
            "s_hat": lo, "core_lo": min(core), "core_hi": max(core),
            "core_n": len(core), "n_surv": len(surv), "multiples": mult[:8]}


# --------------------------------------------------------------------- 수집

def amount_to_won(text):
    mt = AMOUNT.search(text or "")
    if not mt:
        return None
    try:
        return int(mt.group(0).replace(",", ""))
    except ValueError:
        return None


def match_pool(label):
    flat = (label or "").replace(" ", "")
    if TOTAL in flat:
        return TOTAL
    for name in POOL_NAMES:                   # 긴 이름부터: 복승식 ⊄ 삼복승식
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


def collect(payload):
    """한 경주에서 풀별 d 목록과 금액을 뽑는다."""
    race, rows = parse_race(payload, sections=("body", "foot"))
    pages = page_cells(rows)
    per_pool = collections.defaultdict(list)
    amounts = {}
    for (pk, variant), (body, foot, hcol) in sorted(pages.items()):
        if variant:                           # 고정마 페이지(3Bc/3Both)는 제외
            continue
        for cell in foot:
            if ":" in cell.cell_raw:
                label, _, amt = cell.cell_raw.partition(":")
                name = match_pool(label)
                if name:
                    amounts[name] = amount_to_won(amt)
        for r in body:
            if hcol is not None and r.col == hcol:
                continue
            if not ODDS.match(r.cell_raw):
                continue
            pool = (r.col_group if r.col_group in POOLS else None) if pk == "Scm" \
                else next((k for k, v in POOLS.items() if v["page"] == pk), None)
            if pool is not None:
                per_pool[pool].append(round(float(r.cell_raw) * 10))
    return race, per_pool, amounts


def upper_bound(pool, amounts):
    """가려진 풀 하나만 미지로 두었을 때의 잔여액 상한(원)."""
    total = amounts.get(TOTAL)
    if not total:
        return None
    known = 0
    for name in ("단승식", "연승식", "복승식"):
        if name == pool:
            continue
        v = amounts.get(name)
        if v is None:
            return None
        known += v
    return total - known


def probe_race(payload, budget):
    race, per_pool, amounts = collect(payload)
    rec = {
        "race_id": race.race_id, "date": race.date, "meet": race.meet,
        "n_registered": race.n_registered, "n_scratched": len(race.scratched),
        "n_starters": race.n_registered - len(race.scratched),
        "problems": race.problems, "amounts": amounts, "pools": {},
    }
    for pool in KNOWN + UNKNOWN:
        ds = per_pool.get(pool)
        if not ds:
            continue
        cfg = POOLS[pool]
        cap = upper_bound(pool, amounts)
        info = {"n_cells": len(ds),
                "n_cap": sum(1 for d in ds if d == CAP_D),
                "n_floor": sum(1 for d in ds if d == FLOOR_D),
                "d_max": max(ds), "cap_won": cap}
        if cap is None or cap <= 0:
            info["status"] = "상한없음"
        else:
            c = 100 * cfg["p"]
            res = recover(ds, cfg["p"], cfg["q"], cfg["m"], c * (cap // 100), budget)
            info.update(res)
            if pool in KNOWN:
                true_S = amounts.get(pool)
                info["S_true"] = true_S
                if true_S and res.get("status") == "복원":
                    s_true = true_S // 100
                    info["hit_exact"] = (res["s_hat"] == s_true)
                    info["hit_core"] = (res["core_lo"] <= s_true <= res["core_hi"])
                    info["rel_err"] = res["s_hat"] / s_true - 1
            else:
                if res.get("status") == "복원":
                    info["S_hat"] = res["s_hat"] * 100
                    info["share"] = res["s_hat"] * 100 / cap
        rec["pools"][pool] = info
    return rec


# --------------------------------------------------------------------- 실행

def run_batch(paths, budget):
    recs, errs = [], []
    for path in paths:
        try:
            payload = json.loads(gzip.decompress(pathlib.Path(path).read_bytes()))
        except Exception as exc:                      # noqa: BLE001
            errs.append({"file": str(path), "error": f"읽기: {exc}"})
            continue
        try:
            recs.append(probe_race(payload, budget))
        except Exception as exc:                      # noqa: BLE001
            errs.append({"file": str(path), "error": f"파싱: {exc}"})
            continue
    return recs, errs


def pick(archive, n, seed, year=None):
    """표본을 결정적으로 고른다.  같은 인자면 같은 경주가 뽑힌다."""
    files = []
    for m in months(archive, year=year):
        files.extend(str(f) for f in m.files)
    files.sort()
    if n >= len(files):
        return files
    rng = random.Random(seed)
    return sorted(rng.sample(files, n))


def quant(xs, f):
    if not xs:
        return float("nan")
    v = sorted(xs)
    return v[min(len(v) - 1, int(len(v) * f))]


def report(recs, out):
    w = print
    w(f"\n{'=' * 78}\nP0-S 발매금액 복원 — 표본 {len(recs):,} 경주\n{'=' * 78}")

    for group, title in ((KNOWN, "검증용 풀 (S 를 가리고 복원 후 참값과 대조)"),
                         (UNKNOWN, "표적 풀 (S 가 원자료에 없다)")):
        w(f"\n[{title}]")
        for pool in group:
            infos = [r["pools"][pool] for r in recs if pool in r["pools"]]
            if not infos:
                w(f"  {pool}: 셀 없음")
                continue
            st = collections.Counter(i.get("status", "?") for i in infos)
            w(f"\n  {pool}  ({len(infos):,} 경주)")
            w("    상태: " + ", ".join(f"{k}={v:,}" for k, v in st.most_common()))
            done = [i for i in infos if i.get("status") == "복원"]
            if not done:
                continue
            w(f"    최고배당 d_top 중앙 {quant([i['d_top'] for i in done], .5):,}"
              f"   유효셀 중앙 {quant([i['n_live'] for i in done], .5):,}"
              f"   절단셀 중앙 {quant([i['n_cap'] for i in done], .5):,}")
            w(f"    검사 후보수 중앙 {quant([i['tested'] for i in done], .5):,}"
              f"   90% {quant([i['tested'] for i in done], .9):,}"
              f"   최대 {max(i['tested'] for i in done):,}")
            core = [i["core_n"] for i in done]
            w(f"    식별 덩어리 후보수 중앙 {quant(core, .5):,}"
              f"   90% {quant(core, .9):,}   최대 {max(core):,}")
            if pool in KNOWN:
                ex = [i for i in done if "hit_exact" in i]
                if ex:
                    nx = sum(1 for i in ex if i["hit_exact"])
                    nc = sum(1 for i in ex if i["hit_core"])
                    errs = [abs(i["rel_err"]) for i in ex]
                    w(f"    참값 대조 {len(ex):,} 경주 -> "
                      f"최소해=참값 {nx:,} ({nx / len(ex):.1%}), "
                      f"덩어리가 참값 포함 {nc:,} ({nc / len(ex):.1%})")
                    w(f"    최소해 상대오차 중앙 {quant(errs, .5):.2e}"
                      f"   90% {quant(errs, .9):.2e}   최대 {max(errs):.2e}")
            else:
                sh = [i["share"] for i in done if "share" in i]
                if sh:
                    w(f"    복원한 S / 잔여액 상한: 중앙 {quant(sh, .5):.3f}"
                      f"   10% {quant(sh, .1):.3f}   90% {quant(sh, .9):.3f}")

    # 표적 두 풀을 함께 복원한 경주에서, 합이 잔여액을 넘지 않는지 본다.
    both, over = 0, 0
    ratios = []
    for r in recs:
        a = r["pools"].get("쌍승식", {})
        b = r["pools"].get("복연승식", {})
        cap = a.get("cap_won")
        if a.get("status") != "복원" or b.get("status") != "복원" or not cap:
            continue
        both += 1
        tot = a["S_hat"] + b["S_hat"]
        ratios.append(tot / cap)
        if tot > cap:
            over += 1
    w("\n[과대식별 검정 — 쌍승 + 복연승 <= 잔여액(쌍승+복연승+삼복승+삼쌍승)]")
    if both:
        w(f"  두 풀 모두 복원된 경주 {both:,}   상한 위반 {over:,} ({over / both:.1%})")
        w(f"  (쌍승+복연승)/잔여액: 중앙 {quant(ratios, .5):.3f}"
          f"   10% {quant(ratios, .1):.3f}   90% {quant(ratios, .9):.3f}")
        w("  삼복승·삼쌍승 몫이 남아야 하므로 이 비율은 1 보다 작아야 한다.")
    else:
        w("  해당 경주 없음")
    w(f"\n전체 결과: {out}\n")


# --------------------------------------------------------------------- 자체검증

def selftest(n_trials=40, seed=7):
    """합성자료로 알고리즘의 무결성을 확인한다.  아카이브가 없어도 돈다."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n_trials):
        nh = rng.choice((11, 12, 13, 14, 15, 16))
        S = rng.choice((20_000_000, 50_000_000, 100_000_000, 200_000_000))
        w = sorted((rng.gammavariate(0.7, 1.0) for _ in range(nh)), reverse=True)
        t = sum(w)
        p = [x / t for x in w]
        q = []
        for i in range(nh):
            for j in range(nh):
                if i != j:
                    q.append(p[i] * p[j] / (1 - p[i]))
        q = [x * math.exp(rng.gauss(0, 0.45)) for x in q]
        tq = sum(q)
        ns = [max(1, round((S // 100) * x / tq)) for x in q]
        s_true = sum(ns)
        X = 7300 * s_true
        ds = [min(int(math.floor(X / (100 * n) / 10 + 0.5)), CAP_D) for n in ns]
        res = recover(ds, 73, 100, 1, 7300 * (s_true * 3), 8_000_000)
        rows.append((res, s_true))
    ok = [(r, s) for r, s in rows if r["status"] == "복원"]
    ex = sum(1 for r, s in ok if r["s_hat"] == s)
    co = sum(1 for r, s in ok if r["core_lo"] <= s <= r["core_hi"])
    print(f"자체검증 {len(rows)} 회: 복원 {len(ok)}, 최소해=참값 {ex}, "
          f"덩어리가 참값 포함 {co}")
    if ok:
        errs = [abs(r["s_hat"] / s - 1) for r, s in ok]
        print(f"  최소해 상대오차 최대 {max(errs):.2e}, "
              f"검사 후보수 최대 {max(r['tested'] for r, _ in ok):,}")
    return 0 if ok and co == len(ok) else 1


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("outputs/p0_s_recover.json"))
    ap.add_argument("--sample", type=int, default=200, metavar="N")
    ap.add_argument("--seed", type=int, default=20260812)
    ap.add_argument("--year", type=int)
    ap.add_argument("--budget", type=int, default=5_000_000,
                    metavar="N", help="경주·풀당 검사할 후보 s 의 상한")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--selftest", action="store_true",
                    help="아카이브 없이 합성자료로 알고리즘만 확인한다")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.archive or not args.archive.is_dir():
        sys.exit("아카이브 없음: --archive 를 주거나 --selftest 를 쓴다")

    files = pick(args.archive, args.sample, args.seed, args.year)
    if not files:
        sys.exit("읽을 것이 없다")
    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"{len(files):,} 경주 표본, 워커 {workers}, 예산 {args.budget:,}",
          file=sys.stderr)

    chunks = [files[i::workers] for i in range(workers)]
    t0 = time.time()
    recs, errs = [], []
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(run_batch, ch, args.budget) for ch in chunks if ch]
        for k, fut in enumerate(cf.as_completed(futs), 1):
            try:
                r, e = fut.result()
            except Exception as exc:                  # noqa: BLE001
                errs.append({"chunk": k, "error": str(exc)})
                continue
            recs.extend(r)
            errs.extend(e)
            print(f"  [{k}/{len(futs)}] {len(r)} 경주", file=sys.stderr)

    recs.sort(key=lambda r: r["race_id"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"archive": str(args.archive), "sample": len(recs), "seed": args.seed,
         "budget": args.budget, "elapsed_seconds": round(time.time() - t0, 1),
         "races": recs, "errors": errs},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report(recs, args.out)
    if errs:
        print(f"오류 {len(errs):,}건은 결과 파일에 있다.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
