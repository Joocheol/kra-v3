# 전체 경주 우측검열 꼬리분포: 선택편향을 제거한 KRA3 후속 평가

## 핵심 판정

**비-상한 경주만 골라 학습하는 설계는 폐기하고, 전체 경주에서 `9999.9`를 우측검열 관측으로 포함하는 설계를 유지한다.**

이 변경만으로 GPD의 tail shape가 완전히 달라졌다.

- 비-상한 경주 선택표본 GPD: `xi≈-0.14~-0.16` → 약 1.4만배의 잘못된 유한 endpoint
- 전체 경주 censored GPD: **`xi≈+0.57~+0.59`** → 유한 endpoint 없음, 실제 2만~5만배 공식 지급배당과 구조적으로 양립

따라서 앞 단계에서 발견한 가짜 유한 endpoint는 GPD 자체의 문제가 아니라 **경주 전체가 uncapped인 표본을 고른 선택효과**가 핵심 원인이었음을 강하게 시사한다.

다만 전체 경주 GPD를 바로 최종 복원 prior로 채택하지는 않는다. 2022–2024에서 학습한 모든 후보가 2025의 cap 발생비율을 체계적으로 과대예측하며, GPD/lognormal/stretched-exponential의 OOS likelihood 차이는 매우 작다. 다음 단계는 분포 family보다 **연도·유동성·상태공간 조건부 모형**이다.

## 설계

2022–2025 strict-feasible 삼쌍승 경주 9,671개를 모두 사용한다.

threshold `u=3000,5000,7000`에서

- `u <= D < 9999.85`: exact observation
- 표시 `9999.9`: `D >= 9999.85`인 right-censored observation

으로 처리한다.

2022–2024를 학습, 2025를 시간외 검증으로 두고 다음 family를 동일한 censored likelihood에서 비교한다.

- Pareto
- exponential excess
- lognormal
- stretched-exponential
- generalized Pareto (GPD)

## GPD 추정치

| u | train exact | train censored | sigma | xi | 2025 mean LL |
|---:|---:|---:|---:|---:|---:|
| 3,000 | 1,816,797 | 1,166,582 | 5,590 | **0.5866** | -6.557888 |
| 5,000 | 989,282 | 1,166,582 | 6,798 | **0.5707** | -5.191643 |
| 7,000 | 476,073 | 1,166,582 | 7,933 | **0.5741** | -3.438555 |

`xi`가 threshold에 대해 매우 안정적이며 모두 양수다. EVT 해석상 이는 heavy, unbounded upper tail과 일치한다.

비-상한 경주 선택표본에서 `xi<0`였던 것과 부호까지 반대다. 이는 **whole-race selection이 tail class 자체를 뒤집을 수 있을 만큼 강했다**는 뜻이다.

## 2025 시간외 likelihood

threshold별 차이는 작지만 GPD가 전체 평균에서 가장 높다.

| family | 3천 LL | 5천 LL | 7천 LL | 평균 LL |
|---|---:|---:|---:|---:|
| Pareto | -6.573525 | -5.194962 | -3.438971 | -5.069153 |
| Exponential | -6.562803 | -5.193546 | -3.439057 | -5.065136 |
| Lognormal | -6.557893 | -5.191645 | -3.438555 | -5.062698 |
| Stretched exponential | -6.557946 | -5.191653 | -3.438555 | -5.062718 |
| **GPD** | **-6.557888** | **-5.191643** | **-3.438555** | **-5.062695** |

GPD가 숫자상 1위지만 lognormal과 stretched-exponential과의 차이는 매우 작다. 따라서 `BEST_OOS_CENSORED_LL = GPD`를 **생성법칙 확정**으로 해석하지 않는다.

## higher-threshold count 예측

2025에서 실제 cap 셀까지 모두 `v` 이상으로 포함해 예측했다.

전체 target 조합의 평균/최대 상대오차:

| family | 평균 상대오차 | 최대 상대오차 |
|---|---:|---:|
| **Pareto** | **10.51%** | 26.23% |
| Exponential | 11.79% | **15.78%** |
| Lognormal | 10.96% | 20.60% |
| Stretched exponential | 10.99% | 20.54% |
| GPD | 10.95% | 20.62% |

즉 likelihood에서는 GPD가 근소한 1위지만 count prediction에서는 family 간 우열이 엇갈린다. **전역 family 하나를 고르는 것보다 조건부 구조를 찾는 것이 더 중요**하다는 신호다.

## 가장 중요한 미적합: 2025 cap fraction의 체계적 과대예측

2025 실제 `9999.9` 비율과 2022–2024 학습모형의 예측:

### u=3000 조건부

- 실제: **32.42%**
- Pareto: 40.93%
- Exponential: 37.54%
- Lognormal: 39.10%
- Stretched: 39.08%
- GPD: 39.11%

### u=5000 조건부

- 실제: **47.01%**
- 예측: 대략 53.5–54.7%

### u=7000 조건부

- 실제: **65.16%**
- 예측: 대략 70.9–71.1%

따라서 모든 family가 같은 방향으로 2025 cap fraction을 과대예측한다. 이는 family 선택보다 **학습기와 검증기의 시장 유동성·출전두수·상태공간·연도 구성이 달라졌음**을 우선 의심해야 한다.

## Gabaix 계열 분석이 여기까지 준 결론

1. 단순 power law/Pareto를 가정하면 안 된다.
2. 비-상한 경주 안에는 강한 scale-invariant rank-size 구조가 존재한다.
3. 그러나 그 경주들은 capped 경주와 다른 regime이며, 선택표본 GPD는 실제 support를 심각하게 잘못 추정한다.
4. 전체 경주를 right-censoring으로 포함하면 GPD가 `xi≈+0.57`의 heavy tail로 바뀌고 실제 극단배당과 양립한다.
5. 그럼에도 2025 cap rate를 모든 family가 과대예측하므로 **다음 문제는 tail family가 아니라 conditional scaling**이다.

## 다음 단계

Gabaix et al. (2003)의 거래량/스케일링 관점을 KRA3에 맞게 제한적으로 평가한다.

경주별로

- 총 삼쌍승 마권 수 `T`
- 상태 수 `K=h(h-1)(h-2)`
- 상태당 평균 마권 수 `T/K`
- capped-cell 비율 `C/K`
- visible-tail curvature

를 결합하여, 2025의 cap-rate 하락과 capped/uncapped regime 차이가 **liquidity per state** 및 field size로 설명되는지 본다.

또한 pari-mutuel 회계식

\[
D \approx 0.73T/n
\]

에서 상대적 마권밀도 `n/(T/K)`를 쓰면

\[
\frac{n}{T/K}\approx\frac{0.73K}{D},
\]

이므로 `D/K`는 상태공간 크기를 제거한 역상대인기도 척도가 된다. raw odds가 아니라 이 정규화 척도에서 rank-size 전이가 개선되는지도 검증한다.

### 무투표 주의

`9999.9` 셀에는 `n=0`이 포함될 수 있다. 연속 payout-tail likelihood는 이를 매우 큰 유한배당처럼 근사할 수 있으므로, 최종 `9999.9` 복원에는 zero-ticket atom/부분식별을 별도로 결합해야 한다. 이번 결과는 **tail-class 및 조건부 구조 진단**이지 개별 capped 셀의 점배당 복원 결과가 아니다.
