# 2025 공식 capped 삼쌍승 winner 8건 전체 외부검증

## 최종 판정

**capped-regime에서 학습한 쌍승·삼복승 순위모형은 공식 당첨셀의 점마권 수를 충분히 복원하지 못한다.**

8건 전부를 포함하도록 삼복승이 검열된 2건에는 exacta-only fallback을 사용하고, `residual_min/mid/max`를 모두 적용해 예측구간을 만들었지만:

- midpoint MAE는 균등배분보다 거의 개선되지 않았고
- residual 시나리오가 만든 예측구간은 **8/8건 모두 실제 마권 수를 포함하지 못했다.**

따라서 현재 cross-pool 모형은 **상대순위 신호**로는 검증됐지만, 점값 또는 좁은 불확실성구간을 만드는 모형으로는 기각한다.

## threshold별 요약

| 학습 threshold | uniform MAE | model MAE | uniform MdAPE | model MdAPE | model better | residual-scenario coverage |
|---:|---:|---:|---:|---:|---:|---:|
| 7,000 | 59.50 | **59.00** | 24.55% | **23.52%** | 4/8 | **0/8** |
| 8,000 | 59.50 | 59.25 | 24.55% | 24.01% | 3/8 | **0/8** |
| 9,000 | 59.50 | 59.13 | 24.55% | 24.42% | 3/8 | **0/8** |

7천배가 숫자상 가장 낫지만 개선폭은 매우 작다.

## 7천배 모형의 개별 결과

| race_id | 실제 배당 | 실제 n | 방법 | uniform | model mid | model min–max | APE |
|---|---:|---:|---|---:|---:|---:|---:|
| 2025-01-05_1_08 | 12,425.3 | 384 | exacta+trio | 295 | 306 | 285–328 | 20.3% |
| 2025-01-12_3_02 | 11,194.5 | 340 | exacta+trio | 250 | 255 | 245–265 | 25.0% |
| 2025-09-07_1_01 | 10,796.8 | 322 | exacta+trio | 254 | 251 | 224–278 | 22.0% |
| 2025-10-04_1_02 | 22,926.7 | 162 | exacta+trio | 204 | 206 | 195–217 | 27.2% |
| 2025-11-07_3_03 | 14,299.9 | 172 | exacta-only | 121 | 122 | 116–128 | 29.1% |
| 2025-11-07_3_09 | 18,100.1 | 142 | exacta+trio | 160 | 165 | 162–168 | 16.2% |
| 2025-11-21_3_07 | 49,772.7 | 60 | exacta-only | 157 | 156 | 151–162 | **160.0%** |
| 2025-11-21_3_08 | 17,900.3 | 158 | exacta+trio | 179 | 183 | 176–190 | 15.8% |

가장 극단적인 49,772.7배 사례에서 모형은 실제 60장을 약 156장으로 예측한다. 이는 near-cap cross-pool score가 극단적인 낮은 마권 수를 충분히 구별하지 못한다는 8천·9천배 pseudo-censoring의 신호감쇠와 일치한다.

## 왜 residual min/max로도 구간이 안 넓어지는가

현재 예측구간은

1. cross-pool 상대확률 `p_c`를 한 점으로 고정하고
2. capped 집합 총마권 수 `R`만 residual_min/mid/max로 바꾼 뒤
3. 정수 projection을 수행한다.

따라서 이 구간은 **총량 불확실성만 반영**하고 다음을 반영하지 않는다.

- cross-pool 계수의 표본불확실성
- near-cap에서 rank signal이 약해지는 불확실성
- 같은 score를 가진 셀 사이의 allocation dispersion
- tail/count-shape 불확실성
- `n=0` atom 가능성

8/8 coverage 실패는 현재 문제에서 **allocation uncertainty가 residual-total uncertainty보다 훨씬 크다**는 직접 증거다.

## 복원설계 수정

최종 산출물을 한 개의 `n_hat`으로 만들지 않는다.

대신 각 경주에서 회계적으로 허용되는 정수해를 여러 개 생성한다.

\[
\{n_c^{(m)}: m=1,\ldots,M\}
\]

각 해는 반드시

\[
\sum_c n_c = R,\qquad 0\le n_c\le N_c
\]

를 만족하되, 다음을 확률적/규제항으로 반영한다.

- 유동성 조건부 count/tail shape
- 쌍승·삼복승 rank score
- score 근처의 상당한 dispersion
- zero-ticket 가능성
- residual min/mid/max 또는 전체 feasible residual 범위

그 뒤 공식 winner 8건에서 **prediction interval coverage**를 직접 조정한다. 목표는 단순 MAE 최소화가 아니라, 예를 들어 80%/95% predictive interval이 실제로 그 수준의 coverage를 갖는지 확인하는 것이다.

## FLB에 대한 의미

이 부정적 결과는 주 FLB 결론을 약화시키지 않는다. 극단 `9999.9` 집합 전체의 O/E는 개별 allocation 없이 계산된다.

다만 `9999.9` 내부를 세분해 ‘1.2만배 vs 5만배’ 같은 세부 FLB를 논하려면 **점복원이 아니라 reconstruction uncertainty를 전파한 다중대치/부분식별 결과**가 필요하다.
