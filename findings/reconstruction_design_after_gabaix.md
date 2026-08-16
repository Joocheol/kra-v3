# Gabaix 평가 이후 `9999.9` 복원 설계

## 결론부터

현재 자료는 `9999.9` 셀을 하나의 추정 배당으로 치환하는 **점복원**을 지지하지 않는다.

대신 각 capped 경주에 대해 회계적으로 가능한 여러 정수 마권배분을 생성하고,

\[
\mathcal N_r=\{(n_c)_c:\;\sum_c n_c=R,\;0\le n_c\le N_r\}
\]

안에서 **유동성 조건부 크기정보 + 쌍승·삼복승 순위정보**를 이용해 plausible allocation ensemble을 만드는 것이 현재 가장 방어적이다.

최종 분석단위는 단일 완성 데이터셋이 아니라

\[
\{\text{completed data}^{(m)}:m=1,\ldots,M\}
\]

의 다중대치/부분식별 ensemble이다.

---

# 1. 확정적으로 알려진 것

경주 `r`에서

- 삼쌍승 총 100원 마권 수 `T_r`
- capped 셀 수 `C_r`
- 각 capped 셀의 회계적 상한 `N_r`
- capped 집합 총마권 수 `R_r`의 feasible interval `[R_min,R_max]`

이 알려져 있다.

따라서 실제 capped allocation은 반드시

\[
R_r\in[R_{min},R_{max}],
\]

\[
\sum_{c=1}^{C_r}n_{rc}=R_r,
\]

\[
0\le n_{rc}\le N_r,
\qquad n_{rc}\in\mathbb Z
\]

을 만족한다.

이 제약은 어떤 통계모형보다 우선한다.

---

# 2. Gabaix 평가 이후 폐기한 것

## 단일 Pareto/power law

Rank−1/2 threshold exponent가 3천→5천→7천배에서 3.8→6.5→11.5로 급변하므로 폐기한다.

## 비-상한 경주의 분포를 capped 경주에 그대로 이식

상한 아래 visible 3천–7천배 꼬리곡률부터 capped/uncapped가 크게 다르므로 폐기한다.

## cross-pool softmax 점배분

capped-regime pseudo-censoring에서는 순위예측력이 있지만 공식 winner 8건 점마권 수의 MAE를 거의 개선하지 못하고, residual min/mid/max만 이용한 예측구간 coverage가 0/8이므로 폐기한다.

---

# 3. 살아남은 정보 1: 상태당 유동성 `T/K`

\[
K=h(h-1)(h-2),\qquad L=T/K.
\]

2022–2024에서 `log(T/K)` 하나로 2025 capped-cell 비율 14.5255%를 14.4004%로 예측했다.

또한 전체경주 right-censored GPD의 shape `xi`가 `T/K`가 낮을수록 크게 증가했다.

따라서 `L=T/K`는 capped allocation의 **count-scale / tail-thickness state variable**로 유지한다.

이것은 `9999.9` 셀의 개별 값을 직접 결정하지 않는다. 대신

- zero/small-count가 얼마나 흔해야 하는가
- allocation이 얼마나 집중/분산될 수 있는가

를 조절하는 변수로 사용한다.

---

# 4. 살아남은 정보 2: 쌍승·삼복승 상대순위

실제 capped 경주 내부 pseudo-censoring에서 cross-pool rank Spearman은

- 3천배: 0.782
- 5천배: 0.575
- 7천배: 0.330
- 8천배: 0.214
- 9천배: 0.093

이었다.

단승 Harville 계수는 거의 0이고, 실질적인 정보는

- 쌍승: 1·2착 순서 선호
- 삼복승: 세 마리 집합 선호

에서 온다.

따라서 조합별 score를

\[
s_c=\beta_E x^{exacta}_c+\beta_T x^{trio}_c
\]

로 두되, 실제 cap에 가까워질수록 검증된 계수가 작아지는 사실을 반영해 **강한 point assignment가 아니라 약한 ranking prior**로 쓴다.

---

# 5. 필요한 새 요소: allocation dispersion

공식 winner 8건에서 residual min/mid/max만 바꾼 구간이 0/8 coverage였다는 것은

> 총량 `R`의 불확실성보다 **셀 사이 allocation 불확실성**이 더 크다

는 뜻이다.

따라서 평균배분

\[
p_c\propto\exp(s_c)
\]

주위에 상당한 dispersion을 허용해야 한다.

첫 후보는 Dirichlet–multinomial이다.

\[
P\sim Dirichlet(\kappa p),
\]

\[
n\mid P,R\sim Multinomial(R,P).
\]

- `κ`가 크면 softmax 점배분에 가까움
- `κ`가 작으면 allocation uncertainty가 큼
- `n_c=0`이 자연스럽게 허용됨

`κ`는 capped-regime pseudo-censoring의 2022–2024에서 학습하고 2025의 80%/95% prediction interval coverage로 검증한다.

### 중요한 추가 제약

표준 Dirichlet–multinomial draw는 실제 capped 셀 상한 `N_r`을 넘을 수 있다. 따라서 실제 복원에서는 반드시

1. stochastic allocation target을 생성한 뒤
2. `0≤n_c≤N_r`, `Σn_c=R` feasible set에 bounded integer projection하거나
3. 처음부터 truncated/constrained allocation sampler를 사용해야 한다.

즉 확률모형이 회계제약을 덮어쓰지 못한다.

---

# 6. residual `R`의 처리

`R_min/mid/max` 세 점만으로 uncertainty를 대표하지 않는다.

최종 sensitivity에는 적어도 다음 두 방법을 비교한다.

### 방법 A: identified-set envelope

각 feasible `R` 또는 대표 grid를 따라 allocation ensemble을 생성하고 FLB 결과의 전체 envelope를 보고한다.

### 방법 B: 명시적 sensitivity weights

`R`에 확률적 의미를 부여할 외부근거가 없다면 ‘posterior’라는 표현을 쓰지 않고, 균등/중앙집중 등 몇 가지 가중방식을 sensitivity로만 비교한다.

회계만으로 식별되지 않는 부분에 임의의 확률해석을 숨겨 넣지 않는다.

---

# 7. `n=0` 처리

`9999.9`에는 무투표 셀이 포함될 수 있다.

따라서 payout을 연속확률변수로만 모델링하면 `n=0`을 ‘아주 큰 유한배당’으로 잘못 해석하게 된다.

최종 count formulation에서는

\[
n_c\in\{0,1,2,\ldots,N_r\}
\]

이므로 zero는 별도의 예외가 아니라 자연스러운 정수상태다.

가능하다면 `T/K`별로 pseudo-censoring/회계 identified set이 허용하는 zero-count 비율을 sensitivity parameter로 조정한다.

---

# 8. 검증 순서

최종 후보는 다음 순서를 모두 통과해야 한다.

## A. capped-regime pseudo-censoring

실제 capped 경주의 visible 7천/8천/9천배 셀을 가려

- count MAE
- rank Spearman
- 80%/95% prediction interval coverage
- interval width

를 평가한다.

## B. 공식 capped winner 외부검증

2025 공식 8건뿐 아니라 저장된 2022–2025 공식 43건에서, 해당 연도를 학습에 사용하지 않는 시간분할/leave-year-out 방식이 가능하면 확대한다.

점 MAE보다 **coverage calibration**을 우선한다.

## C. FLB 보존검증

pseudo-censoring 전 완전자료에서 계산한 FLB와

\[
\text{완전자료}\to\text{가상상한}\to\text{복원}
\]

후 FLB를 비교한다.

복원값 자체가 좋아도 FLB를 기계적으로 생성/증폭하면 최종모형으로 채택하지 않는다.

---

# 9. 최종 FLB 보고 구조

## 주결론

개별 allocation이 필요 없는 capped-set O/E와 전체 관측구간 결과.

## 보조결론

검증된 allocation ensemble을 이용한 `9999.9` 내부 세분 결과.

각 세부 FLB 통계는

- 경주일 sampling uncertainty
- residual identified-set uncertainty
- allocation/imputation uncertainty

를 모두 반영한 구간으로 보고한다.

이 구조라면 복원모형이 틀려도 주결론이 무너지지 않고, 복원이 성공할수록 극단꼬리 내부에 대한 해상도만 높아진다.
