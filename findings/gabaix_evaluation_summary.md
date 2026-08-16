# Gabaix 계열 아이디어의 KRA3 평가 종합

## 한 문장 결론

Gabaix 문헌을 따라 검증한 결과, KRA3에서 살아남은 핵심은 **보편적 power law 자체가 아니라 rank-size 진단, extreme-value 사고, 그리고 거래량/상태공간의 스케일링**이다.

특히 `9999.9` 복원은

\[
\boxed{\text{상태당 유동성 }T/K\; +\; \text{회계적 정수제약}\; +\; \text{쌍승·삼복승 상대순위 신호}}
\]

를 중심으로 설계하는 것이 현재 자료에 가장 잘 맞는다.

---

## 논문별 판정

| Gabaix 계열 문헌/아이디어 | KRA3 질문 | 판정 | 실제로 남긴 것 |
|---|---|---|---|
| Gabaix–Ibragimov (2011) Rank−1/2 | 삼쌍승 고배당 tail이 single Pareto인가? | **단순 Pareto 기각** | 높은 log-rank R²만 믿으면 안 된다는 강한 진단; threshold stability 검사 |
| Gabaix (2016) Power Laws in Economics | Pareto가 다른 tail family보다 좋은가? | **Pareto 기각, curved tail 후보 유지** | lognormal/stretched-exponential/GPD를 시간외 경쟁시키는 프레임 |
| Gabaix et al. (2016) EVT 관점 | threshold를 올려도 tail law가 안정적인가? | **uncapped 표본 내부 통과, 전역 전이 기각** | GPD threshold stability, 실제 공식 payout을 이용한 endpoint 외부반증 |
| Gabaix (1999) Zipf/rank-size | 경주별 분포를 정규화하면 공통형태가 있는가? | **uncapped regime 내부 통과, capped 전이 기각** | 경주별 q50/q90 정규화 template; regime별 분포를 나눠야 함 |
| Gabaix et al. (2003) 거래량/스케일링 | 극단배당 발생이 유동성 규모와 연결되는가? | **강하게 지지** | `T/K`가 2025 capped 비율을 시간외 거의 정확히 예측; liquidity-conditioned heavy tail |

---

# 1. Rank−1/2가 실제로 한 일

2022–2024 비-상한 경주에서

- `u=3000`: `ζ≈3.80`
- `u=5000`: `ζ≈6.52`
- `u=7000`: `ζ≈11.45`

로 tail exponent가 급변했다. 2025 higher-threshold 조합 수 예측의 최대 상대오차도 약 103.7%였다.

따라서

\[
P(D>x)\propto x^{-\zeta}
\]

하나로 `9999.9` 이상을 외삽하는 설계는 폐기한다.

**남은 가치:** rank-size 그림은 여전히 강력한 진단도구지만, 복원 prior가 아니라 threshold dependence를 검사하는 도구로 사용한다.

---

# 2. 분포 family 경쟁이 보여준 것

비-상한 경주의 `[u,9999.85)`만 비교하면

- Pareto: 실패
- exponential: 개선
- lognormal: 더 개선
- stretched-exponential: 평균적으로 가장 좋음

이었다.

하지만 threshold마다 최선 family가 조금씩 달랐고 stretched shape도 움직였다. 즉 **한 family가 보편적 생성법칙이라는 증거는 없었다.**

---

# 3. EVT/GPD에서 발견한 선택편향

비-상한 경주만 골라 GPD를 적합하면 `xi≈-0.15`, 약 1.4만배의 finite endpoint가 나왔다. 그러나 실제 2022–2025 KRA capped winner에는 2만~5만배가 다수 존재하고 최고가 49,772.7배이므로 이 endpoint는 외부자료로 기각됐다.

모든 경주를 포함해 `9999.9`를 right-censored observation으로 처리하자 GPD shape가

\[
\xi\approx +0.57
\]

로 부호까지 뒤집혔다.

**핵심 교훈:** `9999.9`가 없는 경주를 학습표본으로 선택하는 것 자체가 tail class를 바꿀 정도로 강한 selection이다.

---

# 4. Rank-size scale invariance: 절반의 성공

비-상한 경주 안에서는 q50/q90로 log-odds를 정규화한 공통 템플릿이 2025 q99를

- 중앙 상대오차 6.7%
- 90%점 상대오차 17.7%

로 예측했다.

즉 같은 regime 안에서는 놀랄 만큼 안정적인 공통형태가 있다.

하지만 실제 `9999.9` 셀을 전부 제거하고 상한 아래 visible 3천–7천배만 비교해도 local curvature 중앙값이

- uncapped: 2.79
- capped: 1.03

으로 달랐다.

따라서 **“uncapped 공통분포를 capped 경주에 이식”하는 원래 가정은 기각**한다.

---

# 5. 가장 강한 양의 결과: 상태당 유동성 `T/K`

경주별

\[
T=\text{삼쌍승 총 100원 마권 수},\qquad
K=h(h-1)(h-2),\qquad
L=T/K
\]

로 두었다.

2022–2024에서 `log(T/K)` 하나만으로 capped-cell 비율을 학습했을 때 2025 전체 비율은

- 실제: 14.5255%
- 예측: **14.4004%**

였다. 오차는 0.125%p에 불과하다.

과거 평균만 쓰면 18.2334%를 예측해 3.708%p 틀렸다.

학습기와 2025에서 같은 `T/K` 분위 안의 cap 비율도 매우 유사했다. 따라서 연도 간 cap-rate 이동의 상당 부분은 **상태당 유동성 구성 변화**로 설명된다.

---

# 6. 유동성 조건부 heavy tail

전체 경주 censored GPD를 `T/K` 5분위별로 적합하면 2025 시간외 성능이 모두 개선됐다.

### cap-fraction 예측 오차

- u=3000: 6.69%p → **2.12%p**
- u=5000: 7.10%p → **2.75%p**
- u=7000: 5.86%p → **2.58%p**

### tail shape

저유동성 1분위의 GPD `xi`는 대략 0.7~0.75, 고유동성 5분위는 약 0.24~0.28이었다.

즉

\[
T/K \uparrow \Longrightarrow \xi \downarrow
\]

로, **상태당 유동성이 낮을수록 고배당 꼬리가 더 두꺼워진다.**

이것이 현재 Gabaix 계열 분석에서 가장 실질적으로 살아남은 scaling result다.

---

# 7. 복원모형에 직접 남는 구조

## 크기/총량

경주별 회계자료가 이미 capped 셀 전체의 총 마권 수

\[
R\in[R_{min},R_{max}]
\]

와 개별 상한

\[
0\le n_c\le N_c
\]

를 강하게 제한한다.

따라서 tail family는 총량 자체를 새로 만들어내는 주모형이 아니라, **허용되는 작은 정수 count들의 shape/regularizer**로 쓰는 편이 맞다.

## 조합별 상대순위

실제 capped 경주 내부 pseudo-censoring에서 쌍승·삼복승 정보는 높은 예측력을 보였다.

- u=3000: Spearman 0.782, MAE 188.6→113.2
- u=5000: Spearman 0.575, MAE 83.3→66.9
- u=7000: Spearman 0.330, MAE 36.2→34.0

단승 Harville과 삼쌍승 내부 same-pool 신호는 결합모형에서 거의 0으로 빠졌고, 실질적 신호는 쌍승·삼복승이 담당했다.

따라서 다른 승식은 **점배당 생성기**가 아니라 capped 집합 안의 **assignment/ranking signal**로 사용한다.

---

# 8. 현재 최종 후보 구조

현재 가장 방어적인 후보는 다음과 같다.

1. `T`, `K`, `T/K` 계산
2. `9999.9`는 right-censored 상태로 유지
3. 회계식으로 `[R_min,R_max]`, `cap_upper` 계산
4. `n=0` 가능성을 유지한 정수 count 공간 구성
5. 유동성 조건부 tail 정보는 count-shape regularizer로 사용
6. 쌍승·삼복승 신호로 capped 셀의 상대순위 결정
7. 총합·개별상한을 만족하도록 integer projection/optimization
8. capped 경주 내부 pseudo-censoring으로 검증
9. 공식 capped winner 지급배당으로 외부검증
10. 검증을 통과한 경우에만 `9999.9` 내부 세부 FLB를 보조분석

주 FLB 결론은 여전히 개별 복원에 의존하지 않는 집합수준 결과를 우선한다.

---

# 9. 아직 닫히지 않은 문제

- `n=0`을 연속 tail의 무한배당과 어떻게 분리할지
- residual min/mid/max 불확실성을 최종 count allocation에 어떻게 전파할지
- 8천·9천배 상한근접 pseudo-censoring에서도 cross-pool 순위신호가 유지되는지
- capped-regime 학습계수가 공식 2025 capped winner 전수에서 실제로 개선되는지
- Claude review가 지적한 rare-event FLB 검정의 null-referenced inference 보강
- odds-band O/E의 endogenous binning artefact를 null simulation으로 분리

이 항목들을 닫기 전에는 개별 `9999.9` 점복원치를 확정 데이터처럼 사용하지 않는다.
