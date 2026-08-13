#!/usr/bin/env python3
"""Evaluate pre-outcome trifecta state prices against realized 2025 top-three order.

The reconstruction uses only odds grids, pool turnover, and frozen accounting
rules.  The recorded arrival is read only after each probability table has been
constructed.  This keeps objective outcome evaluation separate from the
cross-market price-coherence exercise.
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
from decimal import Decimal

import numpy as np

from analyze_cross_market import (
    _won,
    completed_trifecta,
    load_feasible,
    load_race_records,
)
from check_coherence import load_month, norm
from kra.feasible import displayed_ticket_interval

SCENARIOS = ("residual_min", "residual_mid", "residual_max")
FIELDS = [
    "race_id", "date", "model", "scenario", "states", "outcome_capped",
    "outcome_probability", "zero_probability", "nll", "brier",
    "rank_percentile", "accounting_probability_min", "accounting_probability_max",
]


def harville_trifecta(win_odds: dict[int, float]) -> dict[tuple[int, int, int], float]:
    p = norm({horse: 1 / value for horse, value in win_odds.items()})
    triples: dict[tuple[int, int, int], float] = {}
    for a, b, c in itertools.permutations(sorted(p), 3):
        denom2 = 1 - p[a]
        denom3 = 1 - p[a] - p[b]
        if denom2 <= 0 or denom3 <= 0:
            raise ValueError("invalid Harville denominator")
        triples[(a, b, c)] = p[a] * p[b] / denom2 * p[c] / denom3
    total = sum(triples.values())
    return {key: value / total for key, value in triples.items()}


def state_uniform(keys: set[tuple[int, int, int]]) -> dict[tuple[int, int, int], float]:
    value = 1 / len(keys)
    return {key: value for key in keys}


def accounting_outcome_interval(
    race: dict,
    odds: dict[tuple[int, int, int], float],
    info: dict[str, int],
    outcome: tuple[int, int, int],
) -> tuple[float, float, bool]:
    sales = _won(race["sales"]["삼쌍승식"])
    if sales % 100:
        raise ValueError(f"{race['race_id']}: trifecta sales not divisible by 100")
    total = sales // 100
    value = odds[outcome]
    if value != 9999.9:
        candidates = displayed_ticket_interval(sales, Decimal(str(value)))
        if not candidates:
            raise ValueError(f"{race['race_id']}: realized state incompatible with displayed odds")
        return candidates.start / total, (candidates.stop - 1) / total, False

    capped_cells = sum(v == 9999.9 for v in odds.values())
    cap_upper = info["cap_upper"]
    residual_min = info["residual_min"]
    residual_max = info["residual_max"]
    ticket_min = max(0, residual_min - (capped_cells - 1) * cap_upper)
    ticket_max = min(cap_upper, residual_max)
    if ticket_min > ticket_max:
        raise AssertionError(f"{race['race_id']}: empty realized-state accounting interval")
    return ticket_min / total, ticket_max / total, True


def score_distribution(
    distribution: dict[tuple[int, int, int], float],
    outcome: tuple[int, int, int],
) -> tuple[float, bool, float | None, float, float]:
    if outcome not in distribution:
        raise ValueError(f"realized state {outcome!r} absent from forecast support")
    if not math.isclose(sum(distribution.values()), 1.0, abs_tol=1e-12):
        raise AssertionError("forecast does not sum to one")
    realized = float(distribution[outcome])
    zero = realized <= 0
    nll = None if zero else -math.log(realized)
    brier = 1.0 + sum(p * p for p in distribution.values()) - 2.0 * realized
    greater = sum(p > realized for p in distribution.values())
    ties = sum(p == realized for p in distribution.values())
    midrank = 1.0 + greater + 0.5 * (ties - 1)
    rank_percentile = midrank / len(distribution)
    return realized, zero, nll, brier, rank_percentile


def metric_row(
    race: dict,
    model: str,
    scenario: str,
    distribution: dict[tuple[int, int, int], float],
    outcome: tuple[int, int, int],
    accounting: tuple[float, float, bool],
) -> dict[str, object]:
    realized, zero, nll, brier, rank = score_distribution(distribution, outcome)
    pmin, pmax, capped = accounting
    return {
        "race_id": race["race_id"],
        "date": race["date"],
        "model": model,
        "scenario": scenario,
        "states": len(distribution),
        "outcome_capped": int(capped),
        "outcome_probability": format(realized, ".12g"),
        "zero_probability": int(zero),
        "nll": "" if nll is None else format(nll, ".12g"),
        "brier": format(brier, ".12g"),
        "rank_percentile": format(rank, ".12g"),
        "accounting_probability_min": format(pmin, ".12g"),
        "accounting_probability_max": format(pmax, ".12g"),
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


def _model_rows(rows: list[dict[str, object]], model: str, scenario: str = "residual_mid") -> list[dict[str, object]]:
    return [row for row in rows if row["model"] == model and row["scenario"] == scenario]


def _summary(rows: list[dict[str, object]]) -> dict[str, float | int | None]:
    zero = sum(int(row["zero_probability"]) for row in rows)
    finite_nll = [float(row["nll"]) for row in rows if row["nll"] != ""]
    brier = statistics.mean(float(row["brier"]) for row in rows)
    ranks = [float(row["rank_percentile"]) for row in rows]
    probs = [float(row["outcome_probability"]) for row in rows]
    return {
        "races": len(rows),
        "zero": zero,
        "mean_nll": None if zero else statistics.mean(finite_nll),
        "geomean_p": None if zero else math.exp(-statistics.mean(finite_nll)),
        "mean_brier": brier,
        "median_rank": statistics.median(ranks),
        "top_1pct": sum(rank <= .01 for rank in ranks),
        "top_10pct": sum(rank <= .10 for rank in ranks),
        "mean_p": statistics.mean(probs),
    }


def clustered_delta_ci(
    rows: list[dict[str, object]],
    model_a: str,
    model_b: str,
    metric: str,
    *,
    seed: int = 20260813,
    draws: int = 2000,
) -> tuple[float, float, float, int]:
    a = {str(row["race_id"]): row for row in _model_rows(rows, model_a)}
    b = {str(row["race_id"]): row for row in _model_rows(rows, model_b)}
    common = sorted(set(a) & set(b))
    by_date: dict[str, list[float]] = defaultdict(list)
    for race_id in common:
        if metric == "nll" and (a[race_id][metric] == "" or b[race_id][metric] == ""):
            continue
        diff = float(a[race_id][metric]) - float(b[race_id][metric])
        by_date[str(a[race_id]["date"])].append(diff)
    dates = sorted(by_date)
    if not dates:
        raise ValueError("no paired observations for clustered comparison")
    observed = statistics.mean(x for date in dates for x in by_date[date])
    rng = np.random.default_rng(seed)
    boot = np.empty(draws, dtype=float)
    for i in range(draws):
        chosen = rng.choice(dates, size=len(dates), replace=True)
        values = [x for date in chosen for x in by_date[str(date)]]
        boot[i] = float(np.mean(values))
    low, high = np.quantile(boot, [.025, .975])
    return observed, float(low), float(high), sum(len(v) for v in by_date.values())


def make_report(rows: list[dict[str, object]], exclusions: dict[str, int]) -> str:
    models = [
        "trifecta_uniform", "trifecta_position_beta_010", "trifecta_swapped_23",
        "win_harville", "state_uniform",
    ]
    lines = [
        "# 2025년 실제 착순을 이용한 삼쌍승 상태가격 평가", "",
        "## 설계", "",
        "삼쌍승 배당판과 해당 풀 총매출만으로 먼저 상위 1·2·3착의 순서상태 "
        "확률표를 완성한 뒤, 저장된 실제 도착마번의 상위 세 마리를 사후에 읽어 "
        "실현 상태를 채점한다. 복원 단계에는 착순을 사용하지 않는다. 2022--2024년 "
        "가상 상한 검증 뒤 2025년만 최종 평가표본으로 사용한다.", "",
        "주지표는 다항 Brier score(낮을수록 좋음)다. 보조지표로 실현 상태의 "
        "negative log likelihood, 전체 순서조합 중 실현 상태의 예측 mid-rank 백분위, "
        "상위 1%·10% 적중률을 보고한다. `win_harville`은 단승 가격만 이용한 "
        "비순환 기준선이고 `trifecta_swapped_23`은 삼쌍승 2·3착 축을 뒤집은 외부 "
        "반증모형이다.", "",
        "## 표본", "",
        f"2025년 분석 가능 경주는 {len(_model_rows(rows, 'trifecta_uniform')):,}개다. "
        f"제외는 도착마번 부족 {exclusions.get('arrival', 0):,}건, 시장/회계자료 부족 "
        f"{exclusions.get('market', 0):,}건, 활성마와 착순 불일치 "
        f"{exclusions.get('outcome', 0):,}건, 단승 상한가 검열 {exclusions.get('win_censored', 0):,}건이다.", "",
        "## 2025년 주결과 (`R` 중간값)", "",
        "| 모형 | 경주 | 0확률 | 평균 NLL | 실현확률 기하평균 | 평균 Brier | 예측순위 중앙 | 상위 1% | 상위 10% |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    summaries = {}
    for model in models:
        group = _model_rows(rows, model)
        s = _summary(group)
        summaries[model] = s
        nll = "∞" if s["mean_nll"] is None else f"{s['mean_nll']:.5f}"
        gp = "0" if s["geomean_p"] is None else f"{s['geomean_p']:.7f}"
        lines.append(
            f"| {model} | {s['races']:,} | {s['zero']:,} | {nll} | {gp} | "
            f"{s['mean_brier']:.7f} | {s['median_rank']:.3%} | "
            f"{s['top_1pct']:,} | {s['top_10pct']:,} |"
        )

    uniform_state_brier = float(summaries["state_uniform"]["mean_brier"])
    lines.extend(["", "Brier skill은 상태공간 균등분포 대비 `1 - Brier/model / Brier/uniform`으로 계산한다.", "", "| 모형 | Brier skill vs 상태균등 |", "| --- | ---: |"])
    for model in models[:-1]:
        skill = 1 - float(summaries[model]["mean_brier"]) / uniform_state_brier
        lines.append(f"| {model} | {skill:.6f} |")

    lines.extend(["", "## 잔여총량 민감도: 균등배분", "", "| 시나리오 | 평균 Brier | 평균 NLL |", "| --- | ---: | ---: |"])
    for scenario in SCENARIOS:
        s = _summary(_model_rows(rows, "trifecta_uniform", scenario))
        nll = "∞" if s["mean_nll"] is None else f"{s['mean_nll']:.5f}"
        lines.append(f"| {scenario} | {s['mean_brier']:.7f} | {nll} |")

    capped_rows = _model_rows(rows, "trifecta_uniform")
    capped = [row for row in capped_rows if int(row["outcome_capped"])]
    lines.extend(["", "## 실현 삼쌍승 상태의 회계적 식별", ""])
    lines.append(
        f"실현된 1·2·3착 조합 자체가 `9999.9`였던 경주는 {len(capped):,}/"
        f"{len(capped_rows):,}개다. 이 셀의 사전 회계구간은 결과를 보지 않고 계산한다."
    )
    if capped:
        lowers = [float(row["accounting_probability_min"]) for row in capped]
        uppers = [float(row["accounting_probability_max"]) for row in capped]
        lines.append(
            f" 검열 실현상태의 확률 하한 중앙값은 {statistics.median(lowers):.7f}, "
            f"상한 중앙값은 {statistics.median(uppers):.7f}다. 하한이 0인 경주는 "
            f"{sum(x == 0 for x in lowers):,}/{len(capped):,}개다."
        )

    bdiff = clustered_delta_ci(rows, "trifecta_uniform", "win_harville", "brier")
    sdiff = clustered_delta_ci(rows, "trifecta_swapped_23", "trifecta_uniform", "brier")
    lines.extend([
        "", "## 사전 지정 비교: 날짜 cluster bootstrap", "",
        "차이는 앞 모형 - 뒤 모형이다. 음수면 앞 모형의 Brier가 더 작다. 2025년 "
        "날짜를 cluster로 2,000회 재표집한 95% 구간을 병기한다.", "",
        "| 비교 | 평균 Brier 차이 | 95% cluster bootstrap | 경주 |",
        "| --- | ---: | ---: | ---: |",
        f"| trifecta_uniform - win_harville | {bdiff[0]:.8f} | [{bdiff[1]:.8f}, {bdiff[2]:.8f}] | {bdiff[3]:,} |",
        f"| trifecta_swapped_23 - trifecta_uniform | {sdiff[0]:.8f} | [{sdiff[1]:.8f}, {sdiff[2]:.8f}] | {sdiff[3]:,} |",
        "", "## 해석 경계", "",
        "실현 capped 상태가 8건뿐이므로 이 단계는 상한 복원 자체보다 대부분 미검열된 삼쌍승 가격표·풀 정보의 "
        "착순 정렬 평가다. 여기서는 가격표를 정규화한 베팅지분을 확률예측처럼 채점한다. 따라서 좋은 "
        "proper score는 실현 착순과 가격이 더 잘 정렬된다는 뜻이지, 시장이 객관적 "
        "확률을 정확히 안다거나 효율적이라는 인과적 결론이 아니다. 저장된 `arrival`은 "
        "선형 순서만 보존하므로 공동착 구조를 별도로 복원하지 못한다. 검열 셀 사이의 "
        "배분은 여전히 부분식별되어 있으며, 잔여총량 시나리오와 비균등 대안을 함께 "
        "보고한다. 경주별 결과는 `데이터/outcome_evaluation.csv.gz`에 있다.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("데이터"))
    parser.add_argument(
        "--out", type=pathlib.Path,
        default=pathlib.Path("데이터/outcome_evaluation.csv.gz"),
    )
    parser.add_argument(
        "--report", type=pathlib.Path,
        default=pathlib.Path("findings/outcome_evaluation.md"),
    )
    args = parser.parse_args()

    records = load_race_records(args.data / "races.jsonl.gz")
    feasible = load_feasible(args.data / "trifecta_feasible_sets.csv.gz")
    rows: list[dict[str, object]] = []
    exclusions: dict[str, int] = defaultdict(int)
    months = sorted({race["date"][:7] for race in records.values() if race["date"][:4] == "2025"})

    for index, month in enumerate(months, 1):
        print(f"outcome evaluation {index}/{len(months)}: {month}", flush=True)
        markets = load_month(args.data, month)
        month_ids = sorted(race_id for race_id, race in records.items() if race["date"][:7] == month)
        for race_id in month_ids:
            race = records[race_id]
            if len(race.get("arrival") or []) < 3:
                exclusions["arrival"] += 1
                continue
            market = markets.get(race_id)
            info = feasible.get(race_id)
            if market is None or info is None or not market["trifecta"] or not market["win"]:
                exclusions["market"] += 1
                continue
            if any(value == 9999.9 for value in market["win"].values()):
                exclusions["win_censored"] += 1
                continue
            active = set(race["horses"]) - set(race.get("scratched") or [])
            outcome = tuple(race["arrival"][:3])
            if len(set(outcome)) != 3 or not set(outcome).issubset(active):
                exclusions["outcome"] += 1
                continue
            if outcome not in market["trifecta"]:
                exclusions["outcome"] += 1
                continue

            accounting = accounting_outcome_interval(race, market["trifecta"], info, outcome)
            uniform_mid: dict[tuple[int, int, int], float] | None = None
            for scenario in SCENARIOS:
                completed = completed_trifecta(race, market["trifecta"], info, scenario)
                rows.append(metric_row(
                    race, "trifecta_uniform", scenario, completed, outcome, accounting
                ))
                if scenario == "residual_mid":
                    uniform_mid = completed
                    position = completed_trifecta(
                        race, market["trifecta"], info, scenario,
                        allocation="position_independent", beta=.10,
                    )
                    rows.append(metric_row(
                        race, "trifecta_position_beta_010", scenario,
                        position, outcome, accounting,
                    ))
            assert uniform_mid is not None
            swapped = {(a, c, b): p for (a, b, c), p in uniform_mid.items()}
            rows.append(metric_row(
                race, "trifecta_swapped_23", "residual_mid", swapped, outcome, accounting
            ))
            harville = harville_trifecta(market["win"])
            if set(harville) != set(uniform_mid):
                raise ValueError(f"{race_id}: Harville and trifecta support differ")
            rows.append(metric_row(
                race, "win_harville", "residual_mid", harville, outcome, accounting
            ))
            rows.append(metric_row(
                race, "state_uniform", "residual_mid",
                state_uniform(set(uniform_mid)), outcome, accounting,
            ))

    write_csv_gz(args.out, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(make_report(rows, dict(exclusions)), encoding="utf-8")
    print(f"OUTCOME_EVALUATION races={len(_model_rows(rows, 'trifecta_uniform'))} rows={len(rows)} exclusions={dict(exclusions)}")
    print(f"wrote {args.out}")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
