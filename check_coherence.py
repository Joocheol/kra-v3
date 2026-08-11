#!/usr/bin/env python3
"""정합성 검사 — 풀 사이의 산술 항등식으로 파싱을 검정한다.

    python3 check_coherence.py --out 데이터 --month 2018-05

구조 검사(격자가 직사각형인가, 조합이 세 페이지에서 같은가)는 셀이 **어디에**
있는지만 본다. 축이 뒤집혔거나 열이 통째로 한 칸 밀렸어도 구조는 멀쩡하다.

배당은 다르다. 일곱 풀이 전부 같은 잠재 확률분포의 다른 사영이므로, 값들 사이에
반드시 성립해야 하는 항등식이 있다. 그것이 깨지면 값이 잘못 놓인 것이다.

배당 o 에 대한 내재확률은 1/o 에 비례한다. 파리뮤추얼에서 공제율 t 일 때
Σ 1/o = 1/(1-t) 이므로, 풀 안에서 정규화하면 확률이 된다.

  A. 단승 ≥ 연승          부등식. 허용오차가 필요 없다
  B. 오버라운드            풀별 Σ1/o 가 같은 대역에 있는가
  C. 쌍승 축 방향          **축을 결정한다.** 인기마가 1착인 순서의 배당이 반대보다
                          낮아야 한다. Harville 아래 부등호 방향이 확정적이다
  D. 복승 = 쌍승 양방향 합  같은 두 마리, 순서만 다름
  E. 삼쌍승 1착 축         같은 세 마리에서 1·2착만 교환. C 와 같은 논리
  F. 순위 일치             모든 풀의 우승 예측이 같은 쪽을 가리키는가

C·E 가 핵심이다. 축을 뒤집으면 구조 검사는 전부 통과하지만 이 둘이 무너진다.

배당 시장은 완전히 정합적이지 않다(favorite-longshot bias 등). 따라서 이 검사의
기준은 "일치"가 아니라 **"뒤집었을 때보다 압도적으로 나은가"** 이다. 임계값을
고르지 않아도 되는 형태로 짰다.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import itertools
import json
import math
import pathlib
import sys

THETA = "9999.9"


def to_odds(v: str) -> float | None:
    """숫자 셀만 배당으로 읽는다. '----'(취소) '-'(구조적 빈칸)은 값이 아니다.

    θ(9999.9)는 우측 검열점이라 참값이 더 클 수 있으나, 1/9999.9 는 무시할 수
    있는 크기이므로 그대로 넣는다. 빼면 합이 과소평가된다.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def norm(d: dict) -> dict:
    """풀 안에서 정규화. 공제율이 풀마다 달라도 비교 가능해진다."""
    s = sum(d.values())
    return {k: v / s for k, v in d.items()} if s > 0 else {}


def spearman(a: list[float], b: list[float]) -> float:
    def rank(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    n = len(a)
    if n < 2:
        return float("nan")
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return num / (da * db) if da and db else float("nan")


def load_month(out: pathlib.Path, month: str) -> dict:
    """월 하나를 경주별 풀 딕트로 읽는다."""
    races: dict = collections.defaultdict(lambda: {
        "win": {}, "place": {}, "quinella": {}, "qplace": {},
        "exacta": {}, "trio": {}, "trifecta": {},
    })
    for pk in ("Scm", "Both", "Bc", "3Bc", "3Both"):
        p = out / "cells" / f"page_key={pk}" / f"{month}.csv.gz"
        if not p.exists():
            sys.exit(f"missing {p}")
        with gzip.open(p, "rt", encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r["section"] != "body":
                    continue
                rh, ch = r["row_header"], r["col_header"]
                if not rh.isdigit():
                    continue
                o = to_odds(r["cell_raw"])
                if o is None:
                    continue
                race = races[r["race_id"]]
                i = int(rh)
                if pk == "Scm":
                    g = r["col_group"]
                    if g == "단승식":
                        race["win"][i] = o
                    elif g == "연승식":
                        race["place"][i] = o
                    elif g == "복승식" and ch.isdigit() and int(ch) != i:
                        race["quinella"][frozenset((i, int(ch)))] = o
                elif pk == "Bc" and ch.isdigit() and int(ch) != i:
                    race["qplace"][frozenset((i, int(ch)))] = o
                elif pk == "Both" and ch.isdigit() and int(ch) != i:
                    # 헤더 "( 후착 / 선착 )" → 행=2착, 열=1착
                    race["exacta"][(int(ch), i)] = o          # (1착, 2착)
                elif pk == "3Bc" and ch.isdigit():
                    a = int(r["page_variant"])
                    t = frozenset((a, i, int(ch)))
                    if len(t) == 3:
                        race["trio"][t] = o
                elif pk == "3Both" and ch.isdigit():
                    a = int(r["page_variant"])
                    # 헤더 "( 3위 / 2위 )" → 행=3착, 열=2착, 고정마=1착
                    if len({a, i, int(ch)}) == 3:
                        race["trifecta"][(a, int(ch), i)] = o   # (1,2,3착)
    return races


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("데이터"))
    ap.add_argument("--month", default="2018-05")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    races = load_month(args.out, args.month)
    ids = sorted(races)
    if args.limit:
        ids = ids[:args.limit]
    print(f"{args.month}: {len(ids)}경주\n")

    # ---- A. 단승 >= 연승 -------------------------------------------------
    viol = tot = 0
    for rid in ids:
        r = races[rid]
        for h, w in r["win"].items():
            p = r["place"].get(h)
            if p is None:
                continue
            tot += 1
            if p > w + 1e-9:
                viol += 1
    print("A. 단승 >= 연승 (부등식, 허용오차 없음)")
    print(f"   검사 {tot:,}두 중 위반 {viol}  ({viol/tot*100 if tot else 0:.3f}%)")

    # ---- B. 오버라운드 ---------------------------------------------------
    print("\nB. 풀별 오버라운드  Σ1/o  (= 1/(1-공제율))")
    for name in ("win", "place", "quinella", "qplace", "exacta", "trio", "trifecta"):
        vals = [sum(1 / o for o in races[rid][name].values())
                for rid in ids if races[rid][name]]
        if vals:
            vals.sort()
            print(f"   {name:<9} 중앙값 {vals[len(vals)//2]:6.3f}   "
                  f"[{vals[0]:.3f}, {vals[-1]:.3f}]")

    # ---- C. 쌍승 축 방향 (쌍별 방향 검정) ----------------------------
    # 주변화 후 순위상관은 축 판정에 무디다 — 강한 말은 1착으로도 2착으로도
    # 확률이 높아 양쪽 주변합이 비슷해진다. 대신 **쌍의 방향**을 본다.
    # Harville 아래 P(인기마 1착, 비인기마 2착) / P(반대) = (1-p_dog)/(1-p_fav) > 1
    # 이므로 부등호 방향이 확정적이고, 축을 뒤집으면 그대로 뒤집힌다.
    print("\nC. 쌍승 축 방향 — 인기마가 1착인 순서의 배당이 더 낮은가")
    _direction(ids, races, "exacta", lambda ex, f, d, _c: (ex.get((f, d)), ex.get((d, f))))

    # ---- D. 복승 = 쌍승 양방향 합 ---------------------------------------
    print("\nD. 복승{a,b} = 쌍승(a,b) + 쌍승(b,a)  (정규화 후)")
    devs = []
    for rid in ids:
        r = races[rid]
        if not r["quinella"] or not r["exacta"]:
            continue
        pq = norm({k: 1 / o for k, o in r["quinella"].items()})
        pe = norm({k: 1 / o for k, o in r["exacta"].items()})
        agg = collections.Counter()
        for (a, b), p in pe.items():
            agg[frozenset((a, b))] += p
        common = set(pq) & set(agg)
        if len(common) < 3:
            continue
        devs.append(sum(abs(pq[k] - agg[k]) for k in common) / len(common))
    if devs:
        devs.sort()
        print(f"   평균절대편차 중앙값 {devs[len(devs)//2]:.5f}   "
              f"(확률 단위, 조합당)")

    # ---- E. 삼쌍승 1착 축 -----------------------------------------------
    print("\nE. 삼쌍승 1착 축 — 같은 세 마리에서 1·2착만 교환")
    _direction(ids, races, "trifecta",
               lambda tf, f, d, c: (tf.get((f, d, c)), tf.get((d, f, c))),
               third=True)

    # ---- F. 모든 풀의 우승 예측이 같은 쪽인가 ---------------------------
    print("\nF. 풀별 우승 예측 순위의 상호 일치 (단승 기준 순위상관 평균)")
    agg = collections.defaultdict(list)
    for rid in ids:
        r = races[rid]
        if len(r["win"]) < 3:
            continue
        pw = norm({h: 1 / o for h, o in r["win"].items()})
        cand = {
            "연승": {h: 1 / o for h, o in r["place"].items()},
            "복승(주변화)": _marg_pair(r["quinella"]),
            "복연승(주변화)": _marg_pair(r["qplace"]),
            "쌍승(1착축)": _marg_first(r["exacta"]),
            "삼복승(주변화)": _marg_set(r["trio"]),
            "삼쌍승(1착축)": _marg_first(r["trifecta"]),
        }
        for name, d in cand.items():
            hs = sorted(set(pw) & set(d))
            if len(hs) >= 3:
                agg[name].append(spearman([pw[h] for h in hs],
                                          [norm(d)[h] for h in hs]))
    for name in ("연승", "복승(주변화)", "복연승(주변화)", "쌍승(1착축)",
                 "삼복승(주변화)", "삼쌍승(1착축)"):
        xs = agg.get(name) or []
        if xs:
            xs2 = sorted(xs)
            print(f"   {name:<16} 평균 {sum(xs)/len(xs):+.4f}   "
                  f"중앙값 {xs2[len(xs2)//2]:+.4f}   최소 {xs2[0]:+.4f}")
    return 0


def _direction(ids, races, pool, pick, third=False):
    """인기마-먼저 순서가 더 낮은 배당을 갖는지 센다.

    θ(9999.9)가 낀 쌍은 우측 검열이라 방향을 판정할 수 없으므로 따로 뺀다.
    빼지 않으면 판정 불가가 '불일치'로 섞여 검정력이 떨어진다.
    """
    ag = rev = tie = theta = tot = 0
    for rid in ids:
        r = races[rid]
        d_, win = r[pool], r["win"]
        if not d_ or len(win) < 3:
            continue
        hs = sorted(win)
        for i, a in enumerate(hs):
            for b in hs[i + 1:]:
                fav, dog = (a, b) if win[a] < win[b] else (b, a)
                if win[fav] == win[dog]:
                    continue
                thirds = [c for c in hs if c not in (fav, dog)] if third else [None]
                for c in thirds:
                    o1, o2 = pick(d_, fav, dog, c)
                    if o1 is None or o2 is None:
                        continue
                    tot += 1
                    if o1 == 9999.9 or o2 == 9999.9:
                        theta += 1
                    elif o1 < o2:
                        ag += 1
                    elif o2 < o1:
                        rev += 1
                    else:
                        tie += 1
    eff = ag + rev
    if not eff:
        print("   판정 가능한 쌍이 없다")
        return
    print(f"   전체 {tot:,}쌍 (θ 검열 {theta:,} · 동점 {tie:,} 제외 → 판정 {eff:,})")
    print(f"     현재 해석대로   {ag:,}  ({ag / eff * 100:.2f}%)")
    print(f"     축을 뒤집으면   {rev:,}  ({rev / eff * 100:.2f}%)")


def _marg_pair(d: dict) -> dict:
    out = collections.Counter()
    for k, o in d.items():
        for h in k:
            out[h] += 1 / o
    return dict(out)


def _marg_set(d: dict) -> dict:
    out = collections.Counter()
    for k, o in d.items():
        for h in k:
            out[h] += 1 / o
    return dict(out)


def _marg_first(d: dict) -> dict:
    out = collections.Counter()
    for k, o in d.items():
        out[k[0]] += 1 / o
    return dict(out)


if __name__ == "__main__":
    raise SystemExit(main())
