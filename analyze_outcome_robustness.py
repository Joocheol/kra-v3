#!/usr/bin/env python3
"""Robustness checks for realized trifecta-state evaluation.

This extension responds to the first independent review of PR #4.  It keeps
2025 as the confirmatory sample, uses 2022--2024 only to fit a discounted
Harville comparator and as a retrospective replication for models that never
use outcomes, cross-links real capped winners to frozen KRA payouts, and
propagates capped-cell allocation uncertainty adversarially.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import itertools
import math
import pathlib
import statistics
import tempfile
from collections import defaultdict

import numpy as np

from analyze_cross_market import _won, completed_trifecta, load_race_records
from analyze_outcome_evaluation import harville_trifecta, score_distribution, state_uniform
from check_coherence import load_month, norm

PRESPEC_SHA = "11fde096566f586eaa58c019b83c8e8ca10ac264"
PRESPEC_TIME = "2026-08-12T20:55:26Z"
FIRST_RESULTS_SHA = "d799ffc3d852782792344b3872d7c7a3a8b6af99"
FIRST_RESULTS_TIME = "2026-08-12T21:04:00Z"
LAMBDA_MIN = 0.25
LAMBDA_MAX = 1.50
LAMBDA_STEP = 0.005
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20260813

FIELDS = [
    "race_id", "date", "year", "model", "states", "outcome_capped",
    "outcome_probability", "zero_probability", "nll", "brier",
    "rank_percentile", "top10",
]


def load_feasible_extended(path: pathlib.Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not ("2022" <= row["year"] <= "2025" and row["strict_feasible"] == "1"):
                continue
            lo = int(row["feasible_residual_min"])
            hi = int(row["feasible_residual_max"])
            out[row["race_id"]] = {
                "residual_min": lo,
                "residual_mid": (lo + hi) // 2,
                "residual_max": hi,
                "cap_upper": int(row["cap_ticket_upper"]),
                "capped_cells": int(row["capped_cells"]),
                "individual_min": int(row["individual_cap_ticket_min"]),
                "individual_max": int(row["individual_cap_ticket_max"]),
                "total_tickets": int(row["total_tickets"]),
            }
    return out


def fractional_uniform_completion(
    race: dict,
    odds: dict[tuple[int, int, int], float],
    info: dict[str, int],
    scenario: str = "residual_mid",
) -> dict[tuple[int, int, int], float]:
    """Uniform capped-cell *probabilities* without lexicographic integer ties."""
    distribution = completed_trifecta(race, odds, info, scenario)
    capped = [combo for combo, value in odds.items() if value == 9999.9]
    if len(capped) != info["capped_cells"]:
        raise AssertionError(
            f"{race['race_id']}: capped-cell count differs between loaders: "
            f"{len(capped)} != {info['capped_cells']}"
        )
    if not capped:
        return distribution
    total = info["total_tickets"]
    residual = info[scenario]
    share = residual / len(capped) / total
    for combo in capped:
        distribution[combo] = share
    if not math.isclose(sum(distribution.values()), 1.0, abs_tol=1e-12):
        raise AssertionError(f"{race['race_id']}: fractional completion does not sum to one")
    return distribution


def discounted_harville_trifecta(
    win_odds: dict[int, float], lam: float
) -> dict[tuple[int, int, int], float]:
    """Harville with p**lambda discounting at the 2nd/3rd conditional stages.

    lambda=1 exactly recovers ordinary Harville.  The first-place marginal
    remains the normalized win-price distribution.
    """
    if lam <= 0:
        raise ValueError("lambda must be positive")
    p = norm({horse: 1 / value for horse, value in win_odds.items()})
    q = {horse: p[horse] ** lam for horse in p}
    triples: dict[tuple[int, int, int], float] = {}
    for a, b, c in itertools.permutations(sorted(p), 3):
        d2 = sum(q[h] for h in p if h != a)
        d3 = sum(q[h] for h in p if h not in (a, b))
        if d2 <= 0 or d3 <= 0:
            raise ValueError("invalid discounted-Harville denominator")
        triples[(a, b, c)] = p[a] * q[b] / d2 * q[c] / d3
    total = sum(triples.values())
    return {key: value / total for key, value in triples.items()}


def discounted_outcome_nll(
    win_odds: dict[int, float], outcome: tuple[int, int, int], lam: float
) -> float:
    p = norm({horse: 1 / value for horse, value in win_odds.items()})
    a, b, c = outcome
    q = {horse: p[horse] ** lam for horse in p}
    d2 = sum(q[h] for h in p if h != a)
    d3 = sum(q[h] for h in p if h not in (a, b))
    prob = p[a] * q[b] / d2 * q[c] / d3
    return -math.log(prob)


def fit_discount_lambda(contexts: list[dict]) -> tuple[float, float, float]:
    train = [ctx for ctx in contexts if ctx["year"] <= "2024"]
    if not train:
        raise ValueError("no training outcomes for discounted Harville")
    ordinary = statistics.mean(
        discounted_outcome_nll(ctx["win_odds"], ctx["outcome"], 1.0)
        for ctx in train
    )
    n_steps = int(round((LAMBDA_MAX - LAMBDA_MIN) / LAMBDA_STEP))
    candidates = [LAMBDA_MIN + i * LAMBDA_STEP for i in range(n_steps + 1)]
    scored = []
    for lam in candidates:
        nll = statistics.mean(
            discounted_outcome_nll(ctx["win_odds"], ctx["outcome"], lam)
            for ctx in train
        )
        scored.append((nll, lam))
    best_nll, best = min(scored, key=lambda item: (item[0], item[1]))
    if math.isclose(best, LAMBDA_MIN) or math.isclose(best, LAMBDA_MAX):
        raise ValueError(f"discount lambda optimum hit grid boundary: {best}")
    return best, ordinary, best_nll


def row_for_distribution(ctx: dict, model: str, distribution: dict) -> dict[str, object]:
    realized, zero, nll, brier, rank = score_distribution(distribution, ctx["outcome"])
    return {
        "race_id": ctx["race"]["race_id"],
        "date": ctx["race"]["date"],
        "year": ctx["year"],
        "model": model,
        "states": len(distribution),
        "outcome_capped": int(ctx["outcome_capped"]),
        "outcome_probability": format(realized, ".12g"),
        "zero_probability": int(zero),
        "nll": "" if nll is None else format(nll, ".12g"),
        "brier": format(brier, ".12g"),
        "rank_percentile": format(rank, ".12g"),
        "top10": int(rank <= .10),
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


def model_rows(rows: list[dict[str, object]], model: str, years: set[str]) -> list[dict[str, object]]:
    return [row for row in rows if row["model"] == model and row["year"] in years]


def summary(rows: list[dict[str, object]]) -> dict[str, float | int]:
    if not rows:
        raise ValueError("empty summary")
    zero = sum(int(row["zero_probability"]) for row in rows)
    nll = [float(row["nll"]) for row in rows if row["nll"] != ""]
    return {
        "races": len(rows),
        "zero": zero,
        "brier": statistics.mean(float(row["brier"]) for row in rows),
        "nll": math.inf if zero else statistics.mean(nll),
        "rank": statistics.median(float(row["rank_percentile"]) for row in rows),
        "top10": statistics.mean(int(row["top10"]) for row in rows),
    }


def paired_cluster_ci(
    rows: list[dict[str, object]], model_a: str, model_b: str,
    years: set[str], metric: str, *, seed_offset: int = 0,
) -> tuple[float, float, float, int]:
    a = {str(r["race_id"]): r for r in model_rows(rows, model_a, years)}
    b = {str(r["race_id"]): r for r in model_rows(rows, model_b, years)}
    common = sorted(set(a) & set(b))
    by_date: dict[str, list[float]] = defaultdict(list)
    for race_id in common:
        ra, rb = a[race_id], b[race_id]
        if metric == "nll" and (ra["nll"] == "" or rb["nll"] == ""):
            continue
        if metric == "top10":
            diff = float(ra["top10"]) - float(rb["top10"])
        else:
            diff = float(ra[metric]) - float(rb[metric])
        by_date[str(ra["date"])].append(diff)
    dates = sorted(by_date)
    observed = statistics.mean(x for date in dates for x in by_date[date])
    rng = np.random.default_rng(BOOTSTRAP_SEED + seed_offset)
    boot = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    for i in range(BOOTSTRAP_DRAWS):
        chosen = rng.choice(dates, size=len(dates), replace=True)
        vals = [x for date in chosen for x in by_date[str(date)]]
        boot[i] = float(np.mean(vals))
    low, high = np.quantile(boot, [.025, .975])
    return observed, float(low), float(high), sum(len(v) for v in by_date.values())


def _min_sumsq(n: int, total: int, lo: int, hi: int) -> int:
    if n == 0:
        if total != 0:
            raise ValueError("nonzero total with zero cells")
        return 0
    rem = total - n * lo
    if rem < 0 or rem > n * (hi - lo):
        raise ValueError("infeasible equal-box total")
    q, r = divmod(rem, n)
    if lo + q > hi or (r and lo + q + 1 > hi):
        raise ValueError("equal allocation exceeds upper bound")
    return (n - r) * (lo + q) ** 2 + r * (lo + q + 1) ** 2


def _max_sumsq(n: int, total: int, lo: int, hi: int) -> int:
    if n == 0:
        if total != 0:
            raise ValueError("nonzero total with zero cells")
        return 0
    rem = total - n * lo
    cap = hi - lo
    if rem < 0 or rem > n * cap:
        raise ValueError("infeasible concentrated-box total")
    if cap == 0:
        return n * lo * lo
    full, extra = divmod(rem, cap)
    if full > n or (full == n and extra):
        raise ValueError("concentrated allocation exceeds cells")
    value = full * hi * hi
    remaining = n - full
    if extra:
        value += (lo + extra) ** 2
        remaining -= 1
    value += remaining * lo * lo
    return value


def capped_allocation_brier_envelope(ctx: dict) -> tuple[float, float, float, float]:
    """Exact integer envelope conditional on residual_mid and uncapped completion."""
    race, odds, info = ctx["race"], ctx["trifecta_odds"], ctx["info"]
    total = info["total_tickets"]
    baseline = completed_trifecta(race, odds, info, "residual_mid")
    capped = [combo for combo, value in odds.items() if value == 9999.9]
    C = len(capped)
    if C != info["capped_cells"]:
        raise AssertionError(f"{race['race_id']}: envelope loader disagreement")
    if C == 0:
        b = score_distribution(baseline, ctx["outcome"])[3]
        p = baseline[ctx["outcome"]]
        return b, b, p, p
    R = info["residual_mid"]
    lo, hi = info["individual_min"], info["individual_max"]
    if not (C * lo <= R <= C * hi):
        raise AssertionError(f"{race['race_id']}: residual outside capped boxes")
    capped_set = set(capped)
    uncapped_counts = {
        combo: int(round(prob * total))
        for combo, prob in baseline.items() if combo not in capped_set
    }
    if sum(uncapped_counts.values()) != total - R:
        raise AssertionError(f"{race['race_id']}: uncapped completion does not preserve total")
    uncapped_sumsq = sum(n * n for n in uncapped_counts.values())
    outcome = ctx["outcome"]
    if outcome not in capped_set:
        n_out = uncapped_counts[outcome]
        min_sq = uncapped_sumsq + _min_sumsq(C, R, lo, hi)
        max_sq = uncapped_sumsq + _max_sumsq(C, R, lo, hi)
        bmin = 1 + min_sq / total**2 - 2 * n_out / total
        bmax = 1 + max_sq / total**2 - 2 * n_out / total
        p = n_out / total
        return bmin, bmax, p, p
    xlo = max(lo, R - (C - 1) * hi)
    xhi = min(hi, R - (C - 1) * lo)
    if xlo != info["individual_min"] or xhi != info["individual_max"]:
        raise AssertionError(f"{race['race_id']}: frozen individual bounds disagree")
    min_obj = math.inf
    max_obj = -math.inf
    for x in range(xlo, xhi + 1):
        rest = R - x
        min_sq = uncapped_sumsq + x * x + _min_sumsq(C - 1, rest, lo, hi)
        max_sq = uncapped_sumsq + x * x + _max_sumsq(C - 1, rest, lo, hi)
        min_obj = min(min_obj, min_sq / total**2 - 2 * x / total)
        max_obj = max(max_obj, max_sq / total**2 - 2 * x / total)
    return 1 + min_obj, 1 + max_obj, xlo / total, xhi / total


def load_winning_trifecta_payouts(path: pathlib.Path) -> dict[str, dict[str, str]]:
    out = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["pool"] == "trifecta" and row["race_date"].startswith("2025-"):
                out[row["race_id"]] = row
    return out


def calibration_bin(prob: float) -> str:
    if prob <= 0:
        return "0"
    exponent = math.floor(math.log10(prob) * 2) / 2
    return f"10^{exponent:.1f}..10^{exponent + .5:.1f}"


def build_report(
    rows: list[dict[str, object]], contexts: list[dict], lam: float,
    train_plain_nll: float, train_discount_nll: float,
    direct_caps: list[dict[str, object]], envelopes: list[tuple[float, float, float, float]],
    calibration: dict[str, dict[str, list[float]]],
) -> str:
    y25 = {"2025"}
    ytrain = {"2022", "2023", "2024"}
    models = ["trifecta_uniform_fractional", "win_harville_discounted", "win_harville", "trifecta_swapped_23", "state_uniform"]
    s25 = {model: summary(model_rows(rows, model, y25)) for model in models}
    state_brier = float(s25["state_uniform"]["brier"])
    bskill = {m: 1 - float(s25[m]["brier"]) / state_brier for m in models[:-1]}
    lr = math.exp(float(s25["win_harville_discounted"]["nll"]) - float(s25["trifecta_uniform_fractional"]["nll"]))

    comparisons = []
    for idx, metric in enumerate(("brier", "nll", "rank_percentile", "top10")):
        comparisons.append((metric, paired_cluster_ci(rows, "trifecta_uniform_fractional", "win_harville_discounted", y25, metric, seed_offset=idx)))
    plain_rep = paired_cluster_ci(rows, "trifecta_uniform_fractional", "win_harville", ytrain, "brier", seed_offset=10)
    swap_rep = paired_cluster_ci(rows, "trifecta_swapped_23", "trifecta_uniform_fractional", ytrain, "brier", seed_offset=11)
    plain_25 = paired_cluster_ci(rows, "trifecta_uniform_fractional", "win_harville", y25, "brier", seed_offset=12)

    bmin = statistics.mean(x[0] for x in envelopes)
    bmax = statistics.mean(x[1] for x in envelopes)
    pmins = [x[2] for x in envelopes]
    pmaxs = [x[3] for x in envelopes]
    discounted_brier = float(s25["win_harville_discounted"]["brier"])

    lines = [
        "# 실제 착순 평가 강건성·외부검증", "",
        "## 검토 후 설계 보강", "",
        f"최초 착순평가 코드는 `{PRESPEC_SHA}` ({PRESPEC_TIME})에 커밋됐고, 최초 수치 결과 보고서는 "
        f"`{FIRST_RESULTS_SHA}` ({FIRST_RESULTS_TIME})에 커밋됐다. 따라서 아래 추가 분석은 Claude 1차 검토 뒤의 "
        "명시적 사후 강건성 분석이며, 원래 2025 Brier 비교와 구분한다.", "",
        "2025는 원래의 확인표본으로 유지한다. 2022--2024 착순은 원래 삼쌍승 균등완성·일반 Harville·축반전 "
        "모형에 사용된 적이 없으므로 그 세 모형의 retrospective replication으로 보고한다. 동시에 같은 "
        "2022--2024 착순만 사용해 discounted-Harville의 lambda를 적합하고, 그 lambda를 고정해 2025에 적용한다.", "",
        "## discounted Harville", "",
        f"2·3착 조건부에서 단승 정규화확률을 `p^lambda`로 할인한다. lambda=1은 일반 Harville이다. "
        f"2022--2024 NLL을 최소화하는 고정 격자 추정값은 **lambda={lam:.3f}**다. 훈련 평균 NLL은 "
        f"일반 Harville {train_plain_nll:.5f}, discounted {train_discount_nll:.5f}다.", "",
        "## 2025 확인표본", "",
        "| 모형 | 경주 | 평균 Brier | Brier skill vs 상태균등 | 평균 NLL | 예측순위 중앙 | 상위10% |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in models:
        s = s25[model]
        skill = "—" if model == "state_uniform" else f"{bskill[model]:.6f}"
        nll = "∞" if math.isinf(float(s["nll"])) else f"{float(s['nll']):.5f}"
        lines.append(f"| {model} | {int(s['races']):,} | {float(s['brier']):.7f} | {skill} | {nll} | {float(s['rank']):.3%} | {float(s['top10']):.2%} |")
    lines.extend([
        "", f"삼쌍승 균등완성의 실현상태 기하평균 확률은 discounted-Harville의 **{lr:.3f}배**다. "
        f"Brier skill은 {bskill['trifecta_uniform_fractional']:.6f} 대 {bskill['win_harville_discounted']:.6f}다. "
        "이는 score 차이의 규모를 보여주는 비교이며 수익성을 뜻하지 않는다. 삼쌍승 공제율 27%가 별도로 존재하므로 "
        "이 정도의 확률정렬 개선을 베팅수익 또는 시장효율성 증거로 읽을 수 없다.", "",
        "### 날짜 cluster bootstrap: trifecta - discounted Harville", "",
        "| 지표 | 평균 차이 | 95% CI | 경주 | 해석 |",
        "| --- | ---: | ---: | ---: | --- |",
    ])
    label = {"brier":"Brier", "nll":"NLL", "rank_percentile":"rank percentile", "top10":"top10 hit rate"}
    for metric, x in comparisons:
        meaning = "음수=삼쌍승 우위" if metric != "top10" else "양수=삼쌍승 우위"
        lines.append(f"| {label[metric]} | {x[0]:.8f} | [{x[1]:.8f}, {x[2]:.8f}] | {x[3]:,} | {meaning} |")

    lines.extend([
        "", "## 2022--2024 retrospective replication", "",
        "이 표본은 discounted-Harville lambda 적합에는 사용되지만, 아래 원래의 일반-Harville 및 축반전 비교에는 "
        "어떤 outcome fitting도 없다. 따라서 원래 2025 비교의 방향이 과거 세 해에서도 반복되는지만 본다.", "",
        "| 비교 | 평균 Brier 차이 | 95% 날짜-cluster CI | 경주 |",
        "| --- | ---: | ---: | ---: |",
        f"| trifecta - ordinary Harville | {plain_rep[0]:.8f} | [{plain_rep[1]:.8f}, {plain_rep[2]:.8f}] | {plain_rep[3]:,} |",
        f"| swapped23 - trifecta | {swap_rep[0]:.8f} | [{swap_rep[1]:.8f}, {swap_rep[2]:.8f}] | {swap_rep[3]:,} |",
        "", f"참고로 원래 2025 trifecta - ordinary Harville Brier 차이는 {plain_25[0]:.8f} "
        f"[{plain_25[1]:.8f}, {plain_25[2]:.8f}]다.", "",
        "## capped-cell allocation의 adversarial envelope", "",
        "`residual_mid`와 미검열 셀의 정수 완성을 고정하고, `9999.9` 셀 사이의 잔여마권 배분만 모든 허용 정수배분에 "
        "대해 극단화했다. 이는 이전의 residual min/mid/max나 beta=0.10보다 직접적인 allocation 부분식별 진단이다.", "",
        f"2025 평균 Brier의 가능한 범위는 **{bmin:.7f}--{bmax:.7f}**다. 같은 표본의 discounted-Harville 평균 Brier는 "
        f"**{discounted_brier:.7f}**다. 따라서 " + ("가장 불리한 capped 배분에서도 삼쌍승 Brier가 더 낮다." if bmax < discounted_brier else "capped 배분의 최악경계에서는 discounted-Harville 우위를 배제할 수 없다.") , "",
        f"실현상태 확률의 accounting-allocation 하한이 0인 경주는 {sum(p == 0 for p in pmins):,}/{len(pmins):,}개다. "
        "따라서 log score의 완전한 adversarial 최악경계는 이 경주가 하나라도 있으면 무한대이며, NLL에 대해서는 "
        "균등배분 결과를 부분식별에 강건한 점추정치처럼 해석하지 않는다.", "",
        "## 실제 `9999.9` 적중 8건의 외부 지급배당 대조", "",
        "이 진단은 결과를 본 뒤 KRA 지급배당을 사용하므로 2025 proper-score 비교에는 절대 되먹이지 않는다. 또한 "
        "당첨된 capped 셀만 관측되는 선택표본이므로 전체 capped 셀의 대표 정확도로 해석하지 않는다.", "",
        "| race_id | 실제 배당 | 지급식 n 구간 | 지급식 n | 균등완성 배정마권 | 오차(식별 시) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for d in direct_caps:
        actual = "—" if d["ticket_count"] is None else str(d["ticket_count"])
        err = "—" if d["error"] is None else f"{d['error']:.3f}"
        lines.append(f"| {d['race_id']} | {d['actual_odds']} | {d['ticket_min']}--{d['ticket_max']} | {actual} | {d['model_tickets']:.3f} | {err} |")
    identified = [d for d in direct_caps if d["error"] is not None]
    if identified:
        mae = statistics.mean(abs(float(d["error"])) for d in identified)
        lines.extend(["", f"지급식으로 n이 한 값으로 식별된 {len(identified)}/{len(direct_caps)}건에서 균등완성 배정마권의 평균 절대오차는 {mae:.3f}장이다."])

    lines.extend(["", "## calibration 진단 (2025)", "", "각 경주의 모든 순서상태를 예측확률의 0.5 log10 간격으로 묶고, 그 상태가 실제로 발생한 빈도를 비교한다. "
                  "이는 aggregate proper score가 객관적 확률 정확성을 뜻하지 않는다는 주장 경계를 직접 점검한다.", "",
                  "| 모형 | 확률 구간 | 상태수 | 평균 예측확률 | 실현빈도 | 실현/예측 |",
                  "| --- | --- | ---: | ---: | ---: | ---: |"])
    for model in ("trifecta_uniform_fractional", "win_harville_discounted"):
        for bin_name in sorted(calibration[model], key=str):
            count, pred_sum, realized = calibration[model][bin_name]
            meanp = pred_sum / count
            freq = realized / count
            ratio = freq / meanp if meanp > 0 else math.inf
            lines.append(f"| {model} | {bin_name} | {int(count):,} | {meanp:.8f} | {freq:.8f} | {ratio:.3f} |")

    lines.extend([
        "", "## 해석", "",
        "이 추가 분석은 Claude 1차 검토 이후 수행한 강건성 분석이다. discounted-Harville은 알려진 순차조건부 기능형식 "
        "오류와 풀 간 정보차이를 분리하기 위한 더 강한 기준선이다. 2022--2024 복제와 2025 확인표본의 구분, 실제 capped "
        "당첨의 외부대조, allocation envelope, calibration을 함께 보고한다. 어느 결과도 공제 후 수익성, 시장효율성, "
        "참확률의 정확성 또는 인과효과를 직접 식별하지 않는다.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("데이터/outcome_robustness.csv.gz"))
    parser.add_argument("--report", type=pathlib.Path, default=pathlib.Path("findings/outcome_robustness.md"))
    args = parser.parse_args()

    records = load_race_records(args.data / "races.jsonl.gz")
    feasible = load_feasible_extended(args.data / "trifecta_feasible_sets.csv.gz")
    contexts: list[dict] = []
    months = sorted({race["date"][:7] for race in records.values()})
    for idx, month in enumerate(months, 1):
        print(f"outcome robustness {idx}/{len(months)}: {month}", flush=True)
        markets = load_month(args.data, month)
        for race_id in sorted(rid for rid, race in records.items() if race["date"][:7] == month):
            race = records[race_id]
            info = feasible.get(race_id)
            market = markets.get(race_id)
            if info is None or market is None or not market["trifecta"] or not market["win"]:
                continue
            arrival = race.get("arrival") or []
            if len(arrival) < 3:
                continue
            outcome = tuple(arrival[:3])
            active = set(race["horses"]) - set(race.get("scratched") or [])
            if len(set(outcome)) != 3 or not set(outcome).issubset(active) or outcome not in market["trifecta"]:
                continue
            capped_count = sum(v == 9999.9 for v in market["trifecta"].values())
            if capped_count != info["capped_cells"]:
                raise AssertionError(f"{race_id}: capped support differs between loaders")
            if info["individual_min"] != max(0, info["residual_min"] - (capped_count - 1) * info["cap_upper"]):
                raise AssertionError(f"{race_id}: frozen individual minimum differs")
            if info["individual_max"] != min(info["cap_upper"], info["residual_max"]):
                raise AssertionError(f"{race_id}: frozen individual maximum differs")
            uniform = fractional_uniform_completion(race, market["trifecta"], info)
            contexts.append({
                "race": race, "year": race["date"][:4], "info": info,
                "trifecta_odds": market["trifecta"], "win_odds": market["win"],
                "outcome": outcome, "outcome_capped": market["trifecta"][outcome] == 9999.9,
                "uniform": uniform,
            })

    lam, train_plain_nll, train_discount_nll = fit_discount_lambda(contexts)
    print(f"DISCOUNT_LAMBDA {lam:.3f} train_plain_nll={train_plain_nll:.8f} train_discount_nll={train_discount_nll:.8f}")

    rows: list[dict[str, object]] = []
    calibration: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))
    envelopes = []
    for ctx in contexts:
        uniform = ctx["uniform"]
        swapped = {(a, c, b): p for (a, b, c), p in uniform.items()}
        ordinary = harville_trifecta(ctx["win_odds"])
        discounted = discounted_harville_trifecta(ctx["win_odds"], lam)
        state = state_uniform(set(uniform))
        if not (set(uniform) == set(ordinary) == set(discounted) == set(state)):
            raise AssertionError(f"{ctx['race']['race_id']}: comparator support mismatch")
        distributions = {
            "trifecta_uniform_fractional": uniform,
            "trifecta_swapped_23": swapped,
            "win_harville": ordinary,
            "win_harville_discounted": discounted,
            "state_uniform": state,
        }
        for model, dist in distributions.items():
            rows.append(row_for_distribution(ctx, model, dist))
        if ctx["year"] == "2025":
            envelopes.append(capped_allocation_brier_envelope(ctx))
            for model in ("trifecta_uniform_fractional", "win_harville_discounted"):
                dist = distributions[model]
                for key, prob in dist.items():
                    b = calibration_bin(float(prob))
                    cell = calibration[model][b]
                    cell[0] += 1
                    cell[1] += float(prob)
                    cell[2] += int(key == ctx["outcome"])

    payouts = load_winning_trifecta_payouts(args.data / "winning_capped_payouts.csv.gz")
    direct_caps = []
    capped_2025 = [ctx for ctx in contexts if ctx["year"] == "2025" and ctx["outcome_capped"]]
    for ctx in capped_2025:
        race_id = ctx["race"]["race_id"]
        payout = payouts.get(race_id)
        if payout is None:
            raise AssertionError(f"{race_id}: realized capped state lacks frozen payout cross-link")
        combo = tuple(int(payout[x]) for x in ("first_no", "second_no", "third_no"))
        if combo != ctx["outcome"]:
            raise AssertionError(f"{race_id}: payout combination {combo} != outcome {ctx['outcome']}")
        total = ctx["info"]["total_tickets"]
        model_tickets = ctx["uniform"][ctx["outcome"]] * total
        count = int(payout["ticket_count"]) if payout["ticket_count"] else None
        direct_caps.append({
            "race_id": race_id,
            "actual_odds": payout["actual_odds"],
            "ticket_min": payout["ticket_count_min"],
            "ticket_max": payout["ticket_count_max"],
            "ticket_count": count,
            "model_tickets": model_tickets,
            "error": None if count is None else model_tickets - count,
        })
    if len(direct_caps) != len(capped_2025):
        raise AssertionError("not all realized capped states cross-linked")

    write_csv_gz(args.out, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        build_report(rows, contexts, lam, train_plain_nll, train_discount_nll, direct_caps, envelopes, calibration),
        encoding="utf-8",
    )
    print(f"OUTCOME_ROBUSTNESS contexts={len(contexts)} rows={len(rows)} capped_2025={len(capped_2025)}")
    print(f"wrote {args.out}")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
