# Power-law rank-size audit

## 결론

2022--2024년 `9999.9`가 없는 1,543경주의 삼쌍승 마권 순위분포는 **전체 구간에서 단순 power law 하나로 설명되지는 않는다.** 그러나 하위 마권 수 쪽 꼬리 절반은 power law에 상당히 가깝고, 전체 분포에는 `n(r)=C(r+r0)^(-alpha)` 형태의 **shifted power law**가 매우 강하게 적합된다.

동일한 회계 하한·상한을 적용한 2025년 가상상한 복원에서는 shifted power law가 3,000--5,000배에서 자주 최선이지만, 실제 상한에 더 가까운 7,000--9,000배 근접꼬리에서는 기존 empirical rank-profile이 더 낮은 MAE를 보인다. 따라서 power-law 구조는 실재하지만 현재 단계에서 empirical profile을 단순히 대체해서는 안 된다.

## 1. 2022--2024 무상한 1,543경주의 rank-size 적합

| 통계 | 단순 power law | 꼬리 절반 power law | shifted power law |
| --- | ---: | ---: | ---: |
| R² 중앙값 | 0.90946 | 0.96888 | **0.99025** |
| R² 25% 분위 | 0.88854 | 0.95638 | **0.98623** |
| R² ≥ 0.95 경주 비율 | 5.4% | 83.7% | **100.0%** |
| α 중앙값 | 1.0964 | 2.2696 | 2.4837 |

shifted power law는 단순 power law보다 AIC가 좋은 경주가 **100.0%**였고, `ΔAIC = AIC_shifted - AIC_simple`의 중앙값은 **-1186.52**였다. 적합된 shift `r0`의 중앙값은 **116.734**였다.

따라서 log(rank)--log(ticket count)가 전체 범위에서 한 직선이라는 가설은 지지되지 않는다. 반면 작은 마권 수 쪽 꼬리는 상당히 직선적이며, 머리 부분의 굴곡을 shift로 허용하면 전체 rank-size 곡선도 매우 잘 설명된다.

## 2. 교정된 2025 복원 비교 — 공통지지 안

모든 모형은 Claude PR #5 리뷰에서 지적된 비대칭을 제거한 동일한 hidden-total 및 셀별 lower/upper bound를 사용한다.

### 실제 `9999.9`가 있는 경주의 근접꼬리 가상검열

| 가상상한 | uniform | simple power | shifted power | empirical rank-profile | 최저 MAE |
| ---: | ---: | ---: | ---: | ---: | --- |
| 3,000 | 179.499 | 135.656 | **127.539** | 131.774 | shifted power |
| 5,000 | 92.935 | 76.403 | **72.527** | 74.853 | shifted power |
| 7,000 | 54.913 | 51.065 | 46.926 | **43.564** | empirical profile |
| 9,000 | 17.566 | 17.566 | 17.548 | **16.890** | empirical profile |

### `9999.9`가 없는 2025 정상경주의 가상검열

| 가상상한 | uniform | simple power | shifted power | empirical rank-profile | 최저 MAE |
| ---: | ---: | ---: | ---: | ---: | --- |
| 3,000 | 144.166 | 118.672 | **111.143** | 115.431 | shifted power |
| 5,000 | 63.884 | 60.082 | **59.171** | 62.703 | shifted power |
| 7,000 | 65.622 | **65.333** | 65.348 | 65.716 | simple power |
| 9,000 | 154.337 | 154.337 | 154.337 | 154.337 | tie |

## 3. 해석

1. **단순 Zipf/power law 전체분포 가설은 기각하는 편이 맞다.** 전체 R² 중앙값은 0.91이고 R²≥0.95는 5.4%뿐이다.
2. **꼬리는 power-law-like하다.** 꼬리 절반의 R² 중앙값은 0.969이고 83.7%의 경주가 R²≥0.95다.
3. **전체 곡선은 shifted power law가 매우 강하다.** 1,543경주 모두에서 shifted law가 AIC 기준으로 simple law보다 우위이고 R² 중앙값은 0.990이다.
4. **그러나 좋은 in-sample rank-size 적합이 최심부 꼬리 외삽의 우위를 보장하지 않는다.** 실제 상한 경주의 7,000·9,000배 근접꼬리에서는 empirical rank-profile이 shifted power law보다 낮은 MAE다.
5. 따라서 다음 유지규칙은 `shifted power law`를 구조적 기준모형으로 추가하되, 기존 empirical rank-profile을 폐기하지 않는 것이다. 특히 실제 `9999.9` 복원에 가까운 7,000--9,000배 결과는 empirical profile 쪽을 지지한다.

## 4. 다음 검증

모형 교체를 결정하기 전에는 경주일 군집 bootstrap으로 `shifted power - empirical profile`의 paired MAE 차이를 3,000·5,000·7,000·9,000배 각각에서 구간 추정해야 한다. 특히 3,000·5,000배의 shifted-law 우위와 7,000·9,000배의 empirical-profile 우위가 표본변동을 넘어서는지 확인해야 한다.

분석 코드는 `analyze_power_law_rank_audit.py`이며, GitHub Actions의 `power-law-rank-audit` job에서 전체 동결 자료로 재계산되어 성공했다.
