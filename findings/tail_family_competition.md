# 고배당 꼬리분포 경쟁평가: KRA3 2차 평가

## 판정

**stretched-exponential / Weibull-type tail을 상한 아래 분포의 잠정 1위 후보로 유지한다.**

다만 이를 `9999.9` 이상에 바로 외삽하지 않는다. 이번 표본은 경주 전체에 실제 `9999.9` 셀이 없는 경주만 골랐기 때문에, 상한 아래에서 어떤 곡률이 시간외로 가장 잘 재현되는지를 보는 필요조건 검사다. 실제 상한 초과분포의 정당화는 다음 단계 EVT/GPD threshold-stability 검정을 거쳐야 한다.

## 설계

2022–2025년 실제 `9999.9` 셀이 없는 삼쌍승 경주를 사용한다. 2022–2024를 학습, 2025를 시간외 검증으로 둔다.

각 threshold `u=3000,5000,7000`에서 관측구간

\[
u \le D < 9999.85
\]

에 대해 **우측 절단을 likelihood에 명시적으로 반영**하여 다음 네 family를 MLE로 적합했다.

1. Pareto
2. exponential excess
3. lognormal
4. stretched-exponential / Weibull-type tail

평가는 두 축이다.

- 2025의 조건부 평균 log likelihood
- 학습 threshold `u`에서 적합한 모형이 2025의 더 높은 `v=5000,7000,9000` exceedance count를 얼마나 잘 예측하는가

## 2025 시간외 log likelihood

값이 클수록 좋다. `test_vs_best_ll=0`이 해당 threshold의 최우수 모형이다.

| u | family | 2025 평균 log likelihood | 최우수 대비 |
|---:|---|---:|---:|
| 3,000 | Pareto | -8.347606 | -0.029217 |
| 3,000 | Exponential | -8.323835 | -0.005446 |
| 3,000 | Lognormal | -8.320273 | -0.001885 |
| 3,000 | **Stretched exponential** | **-8.318389** | **0** |
| 5,000 | Pareto | -8.087677 | -0.015931 |
| 5,000 | Exponential | -8.077178 | -0.005432 |
| 5,000 | Lognormal | -8.072291 | -0.000545 |
| 5,000 | **Stretched exponential** | **-8.071746** | **0** |
| 7,000 | Pareto | -7.689779 | -0.002939 |
| 7,000 | Exponential | -7.687742 | -0.000902 |
| 7,000 | **Lognormal** | **-7.686840** | **0** |
| 7,000 | Stretched exponential | -7.686855 | -0.000015 |

3천·5천배에서는 stretched-exponential이 가장 좋고, 7천배에서는 lognormal이 극소한 차이로 우세하다. 즉 하나의 family가 모든 threshold를 압도하는 구조는 아니지만, Pareto보다 곡률을 허용하는 두 family가 일관되게 우세하다.

## 2025 higher-threshold 조합 수 예측

전체 여섯 `(u,v)` 조합의 상대오차를 요약하면 다음과 같다.

| family | 평균 상대오차 | 최악 상대오차 |
|---|---:|---:|
| Pareto | 71.33% | 271.58% |
| Exponential | 24.03% | 72.76% |
| Lognormal | 13.08% | 26.04% |
| **Stretched exponential** | **11.40%** | **24.07%** |

stretched-exponential은 사전에 둔 평균오차 25% 기준을 통과하고, 실제로 최악오차도 25% 안에 있다. Lognormal도 매우 근접하지만 최악오차가 26.0%로 경계 밖이다.

주요 개별 예측을 보면 한 family가 모든 지점에서 최선은 아니다.

- `3000→7000`: exponential 오차 약 4.2%가 최선
- `3000→9000`: stretched-exponential 오차 약 5.8%가 최선
- `5000→9000`: lognormal 오차 약 1.1%가 최선
- `7000→9000`: lognormal 오차 약 2.0%가 최선

따라서 stretched-exponential의 판정은 **전역 평균 성능 기준의 잠정 우승**이지, 모든 threshold에서 동일한 생성법칙이 확정됐다는 뜻이 아니다.

## 모수의 방향

stretched-exponential의 적합 shape `k`는 threshold가 올라갈수록

- `u=3000`: `k≈1.484`
- `u=5000`: `k≈1.869`
- `u=7000`: `k≈2.199`

으로 증가한다. `k>1`은 단순 exponential보다 더 빠르게 얇아지는 꼬리와 일치하며, Rank−1/2에서 threshold를 올릴수록 Pareto exponent가 급증했던 결과와도 방향이 맞는다.

하지만 `k` 자체가 threshold에 따라 움직이므로 이 결과 역시 ‘하나의 고정 stretched-exponential 법칙’을 상한 밖까지 자동 외삽할 근거는 아니다.

## 다음 단계

3단계에서는 generalized Pareto distribution(GPD)을 **상한에서 우측 절단된 likelihood**로 적합한다.

검사할 항목은 다음과 같다.

1. threshold `u`를 올릴 때 GPD shape `xi`가 안정되는가
2. scale이 GPD threshold-stability 관계 `sigma_v ≈ sigma_u + xi(v-u)`를 따르는가
3. 2022–2024에서 적합한 GPD가 2025 conditional likelihood와 higher-threshold exceedance를 재현하는가
4. stretched-exponential보다 시간외 예측이 실제로 좋아지는가

GPD도 안정되지 않으면 하나의 전역 꼬리 family를 이용한 `9999.9` 복원은 포기하고, threshold-specific 또는 비모수/경주군별 복원으로 이동한다.
