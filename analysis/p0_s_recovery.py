#!/usr/bin/env python3
"""P0-S: 쌍승식·복연승식의 발매금액 S 를 배당률 격자에서 복원한다.

    python3 analysis/p0_s_recovery.py --archive ~/Dropbox/.../raw_collected_v3_15w
    python3 analysis/p0_s_recovery.py --selftest        # 아카이브 없이 합성검정만

P0-K 가 남긴 문제.  <tfoot> 의 발매금액은 단승·연승·복승과 총매출액뿐이고
쌍승식·복연승식에는 S 가 없다 (19,301 경주 전부).  P2 아이디어의 표적이 쌍승식
절단 배당이므로 S 없이는 격자가 서지 않는다.

되짚으면 S 가 미지수일 뿐 격자 구조는 그대로다.  환급금은

    R = p·S / (q·m·n)          n = 그 조합에 걸린 100원 단위마권 수 (정수)

이고 S 는 100 의 배수이므로 T = S/100 으로 두면 R = 100p·T / (q·m·n) 이다.
반올림 규칙(시행령 제11조, P0-K 에서 확정)은 표시값 d = 10·O 에 대해
R ∈ [10d-5, 10d+5) 를 뜻하므로 셀 하나가 T 에 다음 격자를 놓는다.

    T ∈ [ ceil(qmn(10d-5)/100p),  ceil(qmn(10d+5)/100p) - 1 ]        n = 1,2,3,...

한 셀이 허용하는 T 의 집합은 이 구간들의 합집합이고, 모든 셀의 교집합이 S 의
식별집합이다.  구간 폭은 10qmn/(100p), 간격은 qm(10d-5)/(100p) 이므로 폭이
간격보다 좁을 조건은 n < d 다.  고배당 셀은 n 이 작고 d 가 커서 격자에 빈틈이
크고, 한 셀이 후보를 대략 n/d 배로 줄인다.  저배당 셀은 빈틈이 없어 아무것도
자르지 못하므로 d 내림차순으로 훑다가 비용이 한도를 넘으면 멈춘다.

식별의 한계 -- 정수배 축퇴.  (T, n) 을 (kT, kn) 으로 함께 늘리면 R 이 한 자리도
바뀌지 않는다.  따라서 배당률 격자만으로는 S 가 양의 정수배까지만 식별된다.
Sigma_n = T 도 같은 배율로 늘어나므로 이 축퇴를 깨지 못한다.  깨는 것은 오직
바깥의 상한이다.

    총매출액 - (단승+연승+복승) = 쌍승 + 복연승 + 삼복승 + 삼쌍승 = R_잔여

삼복승·삼쌍승의 S 는 자료에 없으므로 R_잔여는 등식이 아니라 상한이다.  그래도
S <= R_잔여 가 살아남는 배율 k 의 개수를 유한하게 자르고, 두 풀을 함께 놓으면
k1·S1 + k2·S2 < R_잔여 가 조합을 더 줄인다.  이 프로브가 재는 것이 그 개수다.

합성자료에서 확인한 것 (--selftest).  탐색범위를 참값까지로 좁히면 참값보다
작은 해가 한 번도 나오지 않는다.  즉 최소해가 참값이고 나머지는 그 정수배다.
최소 덩어리의 상대폭은 대략 1/d_max 로, 쌍승식에서 0 ~ 0.007% 였다.

무엇을 하지 않는가.  절단 셀(9999.9)의 n 복원은 여기서 하지 않는다.  Sigma_n = T
는 S 의 회계 정의를 가정하므로 복원의 전제로 쓰지 않고 사후 진단으로만 본다.

산술은 전부 정수다.  표준 라이브러리만 쓴다.  아카이브는 읽기 전용으로만 연다.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import gzip
import json
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
CAP_D = 99999          # 9999.9, 우측 절단.  단측 정보뿐이라 자르지 못한다
FLOOR_D = 10           # 1.0, 원금보전.  표시값이 계산값인지 보전값인지 모른다

POOLS = {
    "단승식":   {"page": "Scm",  "p": 8,  "q": 10,  "m": 1},
    "연승식":   {"page": "Scm",  "p": 8,  "q": 10,  "m": None},
    "복승식":   {"page": "Scm",  "p": 73, "q": 100, "m": 1},
    "쌍승식":   {"page": "Both", "p": 73, "q": 100, "m": 1},
    "복연승식": {"page": "Bc",   "p": 73, "q": 100, "m": 3},
}
TARGETS = ("쌍승식", "복연승식")          # S 가 없어 복원 대상인 풀
KNOWN = ("단승식", "연승식", "복승식")    # S 가 <tfoot> 에 있는 풀
POOL_NAMES = ("삼복승식", "삼쌍승식", "복연승식", "복승식", "쌍승식", "연승식", "단승식")


# ------------------------------------------------------------------- 격자 산술
#
# P = 100p, B = qm 으로 두면 R = P·T/(B·n) 이다.  아래 네 함수가 이 프로브의
# 전부이고 나머지는 자료를 이 형태로 옮기는 일뿐이다.

def t_bounds(P, B, n, d):
    """n 이 주어졌을 때 표시값 d 를 내는 T 의 정수 구간 [lo, hi]."""
    # P·T >= B·n·(10d-5) 이고 P·T < B·n·(10d+5)
    return -(-B * n * (10 * d - 5) // P), -(-B * n * (10 * d + 5) // P) - 1


def n_span(P, B, d, a, b):
    """T 가 [a, b] 안일 때 걸릴 수 있는 n 의 범위 [lo, hi]."""
    lo = P * a // (B * (10 * d + 5)) + 1
    return (1 if lo < 1 else lo), P * b // (B * (10 * d - 5))


def refine(intervals, P, B, d, cap):
    """표시값 d 인 셀 하나로 후보 구간들을 자른다.

    비용이 cap 을 넘으면 (None, work, 0).  넘는다는 것은 이 셀의 격자가 후보
    구간보다 촘촘해 자를 힘이 없다는 뜻이다.  출력은 정렬돼 있고 맞닿은 구간은
    합쳐진다.
    """
    out, work, total = [], 0, 0
    for a, b in intervals:
        nlo, nhi = n_span(P, B, d, a, b)
        if nhi < nlo:
            continue                                  # 이 구간은 불가능
        work += nhi - nlo + 1
        if work > cap:
            return None, work, 0
        for n in range(nlo, nhi + 1):
            lo, hi = t_bounds(P, B, n, d)
            x = a if a > lo else lo
            y = b if b < hi else hi
            if x > y:
                continue
            if out and out[-1][1] >= x - 1:
                pa, pb = out[-1]
                if y > pb:
                    total += y - pb
                    out[-1] = (pa, y)
            else:
                out.append((x, y))
                total += y - x + 1
    return out, work, total


def recover(ds, P, B, t_hi, budget, max_intervals):
    """셀들의 표시값 목록 ds 로부터 T = S/100 의 식별집합을 구한다.

    돌려주는 구간 목록은 언제나 참값을 포함하는 상위집합이다.  중간에 멈춰도
    (예산·구간수 한도) 건전성은 유지된다.
    """
    cut = sorted({d for d in ds if FLOOR_D < d < CAP_D}, reverse=True)
    intervals, total = [(1, t_hi)], t_hi
    spent = used = 0
    status = "완료"
    for d in cut:
        if total <= 1:
            status = "조기종료"
            break
        nxt, work, tot = refine(intervals, P, B, d, budget - spent)
        spent += work
        if nxt is None:
            status = "중단(비용)"                      # 남은 셀은 더 무겁다
            break
        intervals, total = nxt, tot
        used += 1
        if total == 0:
            status = "모순"
            break
        if len(intervals) > max_intervals:
            status = "중단(구간수)"
            break
    return {"intervals": intervals, "size": total, "cells_used": used,
            "cells_cuttable": len(cut), "spent": spent, "status": status}


def clusters(intervals):
    """정수배 축퇴 구조를 읽는다.  {k: (lo, hi)}.  k=1 덩어리가 최소해다."""
    if not intervals:
        return {}
    t0 = intervals[0][0]
    out = {}
    for a, b in intervals:
        k = round(a / t0) or 1
        if k in out:
            lo, hi = out[k]
            out[k] = (lo if lo < a else a, hi if hi > b else b)
        else:
            out[k] = (a, b)
    return out


def sum_check(ds, P, B, T):
    """Sigma_n = T 대조.  복원의 전제가 아니라 사후 진단이다.

    절단 셀은 베팅 0 일 가능성을 배제하지 않아 하한을 0 으로 둔다.  1.0 셀이
    있으면 경계가 무의미하므로 None.
    """
    lo_sum = hi_sum = 0
    for d in ds:
        if d <= FLOOR_D:
            return None
        if d == CAP_D:
            lo, hi = 0, P * T // (B * (10 * d - 5))
        else:
            lo = P * T // (B * (10 * d + 5)) + 1
            hi = P * T // (B * (10 * d - 5))
            if lo > hi:
                return False
        lo_sum += lo
        hi_sum += hi
    return lo_sum <= T <= hi_sum


# ----------------------------------------------------------------------- 수집

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


def is_total(label):
    flat = (label or "").replace(" ", "")
    return "총" in flat and "매출" in flat


def page_cells(rows):
    """page_key -> (body 행, 마번 열).  고정마 페이지(3Bc/3Both)는 제외."""
    g = collections.defaultdict(list)
    for r in rows:
        if r.spanned or r.section != "body" or r.page_variant:
            continue
        g[r.page_key].append(r)
    return {pk: (body, next((r.col for r in body
                             if r.col_header == HORSE_COL_HEADER), None))
            for pk, body in g.items()}


def probe_race(payload, budget, max_intervals):
    race, rows = parse_race(payload, sections=("body", "foot"))
    pages = page_cells(rows)
    rec = {"race_id": race.race_id, "date": race.date, "meet": race.meet,
           "n_registered": race.n_registered, "n_scratched": len(race.scratched),
           "problems": race.problems, "pools": {}, "skip": None}

    amounts, total = {}, None
    for label, raw in race.sales.items():
        won = amount_to_won(raw)
        if is_total(label):
            total = won
            continue
        pool = match_pool(label)
        if pool:
            amounts[pool] = won
    if total is None or any(amounts.get(k) is None for k in KNOWN):
        rec["skip"] = "발매금액 필드 부족"
        return rec
    residual = total - sum(amounts[k] for k in KNOWN)
    rec.update(total=total, known={k: amounts[k] for k in KNOWN}, residual=residual)
    if residual <= 0 or residual % 100:
        rec["skip"] = f"잔여액 이상 ({residual})"
        return rec

    for pool in TARGETS:
        pk = POOLS[pool]["page"]
        if pk not in pages:
            continue
        body, hcol = pages[pk]
        ds, tokens = [], collections.Counter()
        for r in body:
            if hcol is not None and r.col == hcol:
                continue
            if ODDS.match(r.cell_raw):
                ds.append(round(float(r.cell_raw) * 10))
            else:
                tokens[r.cell_raw] += 1
        if not ds:
            continue
        P, B = 100 * POOLS[pool]["p"], POOLS[pool]["q"] * POOLS[pool]["m"]
        t0 = time.time()
        res = recover(ds, P, B, residual // 100, budget, max_intervals)
        cl = clusters(res.pop("intervals"))
        res.update(
            seconds=round(time.time() - t0, 3), n_cells=len(ds),
            n_censored=sum(1 for d in ds if d == CAP_D),
            n_floored=sum(1 for d in ds if d <= FLOOR_D),
            max_d=max((d for d in ds if d != CAP_D), default=0),
            tokens=dict(tokens), k_list=sorted(cl), n_k=len(cl))
        if cl:
            lo, hi = cl[min(cl)]
            res.update(base_lo=lo, base_hi=hi, S_base=100 * lo,
                       base_width_ppm=round(1e6 * (hi - lo) / lo, 3),
                       base_size=hi - lo + 1,
                       sum_check_base=sum_check(ds, P, B, lo))
        rec["pools"][pool] = res
    return rec


# ----------------------------------------------------------------------- 집계

def run_chunk(paths, budget, max_intervals, keep):
    recs, ex, errs = [], [], []
    for path in paths:
        try:
            payload = json.loads(gzip.decompress(path.read_bytes()))
        except Exception as exc:                      # noqa: BLE001
            errs.append({"file": path.name, "error": f"읽기: {exc}"})
            continue
        try:
            rec = probe_race(payload, budget, max_intervals)
        except Exception as exc:                      # noqa: BLE001
            errs.append({"file": path.name, "error": f"파싱: {exc}"})
            continue
        if len(ex) < keep:
            ex.append(rec)
        recs.append(rec)
    return {"records": recs, "examples": ex, "errors": errs}


def quant(xs):
    if not xs:
        return {}
    xs = sorted(xs)
    n = len(xs)
    return {"n": n, "최소": xs[0], "1사분위": xs[n // 4], "중앙값": xs[n // 2],
            "3사분위": xs[3 * n // 4], "최대": xs[-1]}


def summarise(recs):
    skips = collections.Counter()
    status = collections.defaultdict(collections.Counter)
    nk = collections.defaultdict(collections.Counter)
    width = collections.defaultdict(list)
    share = collections.defaultdict(list)
    secs = collections.defaultdict(list)
    maxd = collections.defaultdict(list)
    cens = collections.defaultdict(list)
    sums = collections.defaultdict(collections.Counter)
    tokens = collections.Counter()
    nk_by_maxd = collections.defaultdict(collections.Counter)
    pairs = collections.Counter()
    remain = []
    both = 0

    for r in recs:
        if r.get("skip"):
            skips[r["skip"]] += 1
            continue
        base = {}
        for pool, p in r["pools"].items():
            status[pool][p["status"]] += 1
            secs[pool].append(p["seconds"])
            maxd[pool].append(p["max_d"])
            cens[pool].append(p["n_censored"])
            tokens.update(p.get("tokens", {}))
            if "S_base" not in p:
                nk[pool]["0 (모순)"] += 1
                continue
            nk[pool][f"k {p['n_k']}개"] += 1
            width[pool].append(p["base_width_ppm"])
            share[pool].append(round(100.0 * p["S_base"] / r["residual"], 3))
            sums[pool][{True: "일치", False: "불일치", None: "보류"}[
                p["sum_check_base"]]] += 1
            band = ("~10.0" if p["max_d"] < 100 else "~100.0" if p["max_d"] < 1000
                    else "~1000.0" if p["max_d"] < 10000 else "1000.0+")
            nk_by_maxd[pool][f"{band} / k {p['n_k']}개"] += 1
            base[pool] = (p["S_base"], p["k_list"])

        if len(base) == len(TARGETS):
            both += 1
            (s1, k1), (s2, k2) = base[TARGETS[0]], base[TARGETS[1]]
            ok = [(a, b) for a in k1 for b in k2 if a * s1 + b * s2 < r["residual"]]
            pairs[f"{len(ok)}쌍"] += 1
            if len(ok) == 1:
                a, b = ok[0]
                remain.append(round(100.0 * (r["residual"] - a * s1 - b * s2)
                                    / r["residual"], 2))
    return {
        "n_races": len(recs), "skips": skips.most_common(),
        "status": {k: v.most_common() for k, v in status.items()},
        "n_k": {k: v.most_common() for k, v in nk.items()},
        "base_width_ppm": {k: quant(v) for k, v in width.items()},
        "share_of_residual": {k: quant(v) for k, v in share.items()},
        "sum_check": {k: v.most_common() for k, v in sums.items()},
        "seconds": {k: quant(v) for k, v in secs.items()},
        "max_d": {k: quant(v) for k, v in maxd.items()},
        "n_censored": {k: quant(v) for k, v in cens.items()},
        "n_k_by_maxd": {k: sorted(v.items()) for k, v in nk_by_maxd.items()},
        "tokens": tokens.most_common(20),
        "both_recovered": both, "pair_counts": pairs.most_common(),
        "remainder_share": quant(remain),
    }


def report(s, out):
    w = print
    w(f"\n{'=' * 74}\nP0-S 복원 프로브 — {s['n_races']:,} 경주 표본\n{'=' * 74}")
    if s["skips"]:
        w("\n[0] 건너뛴 경주")
        for k, n in s["skips"]:
            w(f"  {k:<34} {n:>7,}")

    w("\n[1] 탐색 상태 — 중단이면 결과는 상위집합(참값 포함은 유지)")
    for pool, rows in sorted(s["status"].items()):
        w(f"  {pool:<10} " + ", ".join(f"{a}={b:,}" for a, b in rows))

    w("\n[2] 살아남은 정수배 k 의 개수 — P2 의 답은 여기서 갈린다")
    w("    k 1개 = S 가 (좁은 구간까지) 복원됨.  2개 이상 = 배율 미결.")
    for pool, rows in sorted(s["n_k"].items()):
        w(f"  {pool:<10} " + ", ".join(f"{a}={b:,}" for a, b in rows))

    w("\n[3] 최소해 덩어리의 상대폭 (ppm, 100만분율) — 복원 정밀도")
    for pool, v in sorted(s["base_width_ppm"].items()):
        if v:
            w(f"  {pool:<10} " + ", ".join(f"{a}={b}" for a, b in v.items()))

    w("\n[4] 최소해 S 의 잔여액 대비 비율(%) — k=1 이 그럴듯한지")
    for pool, v in sorted(s["share_of_residual"].items()):
        if v:
            w(f"  {pool:<10} " + ", ".join(f"{a}={b}" for a, b in v.items()))

    w("\n[5] 최고 비절단 배당과 배율 개수의 관계")
    for pool, rows in sorted(s["n_k_by_maxd"].items()):
        w(f"  {pool}")
        for k, n in rows:
            w(f"      {k:<26} {n:>7,}")

    w("\n[6] 두 풀 결합 — k1·S1 + k2·S2 < 잔여액 을 만족하는 (k1,k2) 쌍의 수")
    w(f"  두 풀 모두 해를 얻은 경주: {s['both_recovered']:,}")
    for k, n in s["pair_counts"]:
        w(f"  {k:<24} {n:>7,}")
    if s["remainder_share"]:
        w("  쌍이 유일할 때 잔여분(삼복승+삼쌍승 몫) 비율(%): " +
          ", ".join(f"{a}={b}" for a, b in s["remainder_share"].items()))

    w("\n[7] Sigma_n 대조 (사후 진단 — 복원에는 쓰지 않았다)")
    for pool, rows in sorted(s["sum_check"].items()):
        w(f"  {pool:<10} " + ", ".join(f"{a}={b:,}" for a, b in rows))

    w("\n[8] 비용과 자료 형편")
    for pool in sorted(s["seconds"]):
        for name, tbl in (("시간(초)", s["seconds"]), ("max_d", s["max_d"]),
                          ("절단셀수", s["n_censored"])):
            w(f"  {pool:<10} {name:<9} " +
              ", ".join(f"{a}={b}" for a, b in tbl[pool].items()))

    if s["tokens"]:
        w("\n[9] 배당률로 파싱되지 않은 셀")
        for tok, n in s["tokens"]:
            w(f"  {tok!r:<20} {n:>12,}")

    w(f"\n전체 결과: {out}\n")


# --------------------------------------------------------------------- 자체검정

def synth(S, cells, p, q, m, seed, skew=3):
    """참값 S 를 아는 합성 격자.  skew 가 클수록 소액 조합이 많아져 절단이 는다."""
    rng = random.Random(seed)
    T, P, B = S // 100, 100 * p, q * m
    ws = [rng.random() ** skew + 1e-4 for _ in range(cells)]
    tot, rem = sum(ws), T - cells
    ns = [1 + int(rem * x / tot) for x in ws]
    ns[0] += T - sum(ns)
    ds = []
    for n in ns:
        d = (2 * P * T + 10 * B * n) // (20 * B * n)   # round(P·T/(10·B·n))
        ds.append(CAP_D if d > CAP_D else (FLOOR_D if d < FLOOR_D else d))
    return T, ds, P, B


def selftest(budget, max_intervals):
    cases = [("쌍승식 12두",   30_000_000, 132, 73, 100, 1,  3),
             ("쌍승식 9두",     8_500_000,  72, 73, 100, 1,  3),
             ("쌍승식 16두",   62_400_000, 240, 73, 100, 1,  3),
             ("복연승식 12두",  24_300_000,  66, 73, 100, 3,  3),
             ("복연승식 9두",    9_900_000,  36, 73, 100, 3,  3),
             ("쌍승식 절단多",  30_000_000, 132, 73, 100, 1,  8),
             ("쌍승식 절단多多", 120_000_000, 240, 73, 100, 1, 14),
             ("쌍승식 절단극단", 30_000_000, 132, 73, 100, 1, 20),
             ("복연승식 절단多", 24_300_000,  66, 73, 100, 3, 14)]
    print(f"\n{'=' * 74}\n합성자료 자체검정\n{'=' * 74}")
    print("건전성 = 참값을 버리지 않는다.  최소성 = 참값보다 작은 해가 없다.")
    print("배율 = 상한을 참값의 4배로 두었을 때 살아남는 정수배의 수.\n")
    sound = minimal = True
    for name, S, cells, p, q, m, skew in cases:
        for seed in range(4):
            T, ds, P, B = synth(S, cells, p, q, m, seed, skew)
            r4 = recover(ds, P, B, T * 4, budget, max_intervals)
            cl = clusters(r4["intervals"])
            inside = any(a <= T <= b for a, b in r4["intervals"])
            lo, hi = (cl[min(cl)] if cl else (0, 0))
            ppm = round(1e6 * (hi - lo) / lo, 2) if lo else -1
            sound &= inside
            minimal &= bool(cl) and lo <= T <= hi
            print(f"  {name:<13} seed{seed}  참값포함 {'예' if inside else '아니오 ***'}"
                  f"  최소해=참값 {'예' if lo <= T <= hi else '아니오 ***'}"
                  f"  배율 {len(cl)}개  최소해폭 {ppm:>8.2f}ppm"
                  f"  절단 {sum(1 for d in ds if d == CAP_D):>3}"
                  f"  {r4['status']}")
    print(f"\n건전성: {'통과' if sound else '실패 ***'}   "
          f"최소성: {'통과' if minimal else '실패 ***'}")
    print("정수배 축퇴는 자료의 성질이지 결함이 아니다 — 상한이 배율을 자른다.\n")
    return 0 if (sound and minimal) else 1


# --------------------------------------------------------------------- 실행

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("outputs/p0_s_recovery.json"))
    ap.add_argument("--sample", type=int, default=200, help="무작위 표본 경주 수 (0=전량)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--year", type=int)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--budget", type=int, default=2_000_000, help="경주당 n 열거 상한")
    ap.add_argument("--max-intervals", type=int, default=200_000)
    ap.add_argument("--examples", type=int, default=3)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest(args.budget, args.max_intervals)
    if not args.archive or not args.archive.is_dir():
        sys.exit(f"아카이브 없음: {args.archive}")

    work = months(args.archive, year=args.year)
    files = [f for m in work for f in m.files]
    if not files:
        sys.exit("읽을 것이 없다")
    n_all = len(files)
    if args.sample and args.sample < n_all:
        files = sorted(random.Random(args.seed).sample(files, args.sample))
    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    size = max(1, (len(files) + workers - 1) // workers)
    chunks = [files[i:i + size] for i in range(0, len(files), size)]
    print(f"{len(files):,} 경주 표본 (전체 {n_all:,}), 워커 {workers}", file=sys.stderr)

    t0 = time.time()
    recs, ex, errs, done = [], [], [], 0
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(run_chunk, c, args.budget, args.max_intervals,
                            args.examples) for c in chunks]
        for fut in cf.as_completed(futs):
            try:
                res = fut.result()
            except Exception as exc:                  # noqa: BLE001
                errs.append({"chunk": "?", "error": str(exc)})
                print(f"  덩어리 실패: {exc}", file=sys.stderr)
                continue
            recs.extend(res["records"])
            ex.extend(res["examples"])
            errs.extend(res["errors"])
            done += 1
            print(f"  [{done}/{len(chunks)}] {len(res['records'])} 경주", file=sys.stderr)

    s = summarise(recs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"archive": str(args.archive), "sample": len(recs), "n_all": n_all,
         "seed": args.seed, "budget": args.budget,
         "max_intervals": args.max_intervals,
         "elapsed_seconds": round(time.time() - t0, 1),
         "summary": s, "examples": ex[:args.examples * 4], "errors": errs},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report(s, args.out)
    if errs:
        print(f"오류 {len(errs):,}건은 결과 파일에 있다.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
