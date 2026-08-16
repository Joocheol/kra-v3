# Gabaix 계열 꼬리분포 문헌과 KRA3 적용 로드맵

## 목적

삼쌍승 표시상한 `9999.9`는 극단 고배당 영역을 한 값으로 우측 검열한다. 이 때문에 개별 상한 셀의 실제 배당과 마권 수를 복원하려면, 정상(비-상한) 경주에서 극단 고배당 꼬리의 형태가 얼마나 안정적인지 먼저 확인해야 한다.

이 메모는 Xavier Gabaix의 power-law / rank-size / extreme-value 연구를 KRA3에 어떻게 사용할지 정리하고, 각 아이디어를 **가정이 아니라 검증대상**으로 둔다. 순서는 아래와 같다.

1. Gabaix & Ibragimov (2011) `Rank-1/2` tail exponent 추정
2. Gabaix (2016) power-law 진단 프레임: power law 대 lognormal/exponential/stretched-exponential 경쟁
3. Gabaix et al. (2016) extreme-value 관점: 높은 threshold 초과분포와 threshold 안정성
4. Gabaix (1999) rank-size / scale invariance: 경주별 정규화 후 공통 꼬리형태가 존재하는지
5. Gabaix et al. (2003) 금융시장 scaling: 거래량과 가격 극단값의 공동 scaling에 대한 배경문헌

핵심 원칙은 **power law를 전제하지 않는다**는 것이다. 각 항목은 pseudo-censoring과 시간외 검증을 통과할 때만 실제 `9999.9` 복원에 사용한다.

---

## 왜 마권 수가 아니라 배당/역베팅지분의 상단 꼬리를 보는가

삼쌍승에서 큰 배당은 작은 마권 수에 대응한다. 대략적으로 총 마권 수를 `T`, 공제 후 지급비율을 `q`라 하면

\[
D \approx qT/n,
\]

이므로 `9999.9`는 `n`의 **하단 꼬리**이면서 `D`의 **상단 꼬리**다.

Gabaix 계열의 Pareto / rank-size 방법은 전형적으로 변수의 큰 값, 즉 상단 꼬리를 다룬다. 따라서 KRA3에서 자연스러운 `Size` 변수는

- 실제/표시 배당 `D`, 또는
- 역베팅지분 `1/s`

이다. 마권 수 `n` 자체의 작은 쪽 꼬리에 Rank-1/2 공식을 기계적으로 적용하지 않는다.

---

# 1. Gabaix & Ibragimov (2011): Rank − 1/2

**문헌**

Xavier Gabaix and Rustam Ibragimov, “Rank − 1/2: A Simple Way to Improve the OLS Estimation of Tail Exponents,” *Journal of Business & Economic Statistics* 29(1), 2011, 24–39.

- 저자 페이지: https://xgabaix.scholars.harvard.edu/publications/rank-12-simple-way-improve-ols-estimation-tail-exponents
- NBER working paper: https://www.nber.org/papers/t0342

### 논문의 핵심

Pareto 상단 꼬리에서 보통

\[
\log(\text{Rank}) = a - \zeta \log(\text{Size})
\]

를 OLS로 적합하지만 작은 표본에서 편향이 크다. Gabaix–Ibragimov는

\[
\boxed{\log(\text{Rank}-1/2)=a-\zeta\log(\text{Size})}
\]

를 사용하고, tail exponent의 표준오차를 일반 OLS 표준오차 대신 대략

\[
SE(\hat\zeta)=\hat\zeta\sqrt{2/n}
\]

로 계산하도록 제안한다.

### KRA3에 쓸 수 있는 부분

정상 경주의 고배당 tail에서 threshold `u`를 정하고

\[
X=D/u,\qquad D\ge u
\]

를 size 변수로 둔다. `u=3000,5000,7000`에서 각각 tail exponent를 추정한다.

### 통과 기준

다음이 동시에 성립해야 실제 `9999.9` 복원에 유용하다고 본다.

1. `3000/5000/7000`에서 추정한 `ζ`가 크게 흔들리지 않는다.
2. 2022–2024에서 추정한 `ζ`가 2025에서 비슷하게 재현된다.
3. 낮은 threshold에서 추정한 tail law가 더 높은 threshold의 실제 exceedance count를 시간외에서 잘 예측한다.
4. pseudo-censoring에서 3000/5000/7000 이상의 실제 배당분포를 감추고 복원했을 때 분포적 오차가 단순 대안보다 작다.
5. 특정 경마장·출전두수·매출규모 한 집단만 결과를 주도하지 않는다.

### 기각/보류 기준

- `ζ_3000`, `ζ_5000`, `ζ_7000`가 체계적으로 변함
- log-rank plot에 뚜렷한 곡률이 남음
- 2025 시간외 exceedance를 크게 과대/과소 예측
- power law보다 lognormal 또는 stretched exponential이 일관되게 우세

이 경우 Rank-1/2는 **진단도구**로만 남기고 실제 상한 복원에는 사용하지 않는다.

---

# 2. Gabaix (2016): Power Laws in Economics

**문헌**

Xavier Gabaix, “Power Laws in Economics: An Introduction,” *Journal of Economic Perspectives* 30(1), 2016, 185–206.

- AEA: https://www.aeaweb.org/articles?id=10.1257/jep.30.1.185

### KRA3에서의 역할

이 논문은 power law를 경제자료에서 어떻게 해석하는지에 대한 배경과 진단 프레임을 제공한다. KRA3에서는 “배당 tail이 power law다”라는 주장의 근거가 아니라, **후보 꼬리분포를 비교해야 하는 이유**를 설명하는 방법론 문헌으로 사용한다.

### 비교할 후보

- Pareto / power law
- lognormal
- exponential
- stretched exponential (Weibull tail)
- 필요하면 generalized Pareto distribution (EVT 단계에서)

### 통과 기준

- threshold별·연도별 out-of-sample log likelihood / predictive score에서 power law가 경쟁모형에 비해 안정적으로 우세
- tail exponent와 예측오차가 threshold 선택에 과도하게 민감하지 않음

### 주의

log-log 그림이 대략 직선이라는 이유만으로 power law를 채택하지 않는다. 그림은 탐색이고, 최종 판정은 시간외 예측과 pseudo-censoring 성능으로 한다.

---

# 3. Gabaix et al. (2016): Extreme Value Theory 관점

**문헌**

Xavier Gabaix, David Laibson, Deyuan Li, Hongyi Li, Sidney Resnick, and Casper G. de Vries, “The Impact of Competition on Prices with Numerous Firms,” *Journal of Economic Theory* 165, 2016, 1–24.

- DOI: https://doi.org/10.1016/j.jet.2016.04.001
- 저자 페이지: https://xgabaix.scholars.harvard.edu/publications/impact-competition-prices-numerous-firms

### KRA3에 직접 가져오는 것은 경제모형이 아니라 수학적 관점

이 논문의 경제모형(기업 경쟁/markup)을 경마에 적용하지 않는다. 활용할 부분은 **큰 표본에서 극단값의 거동이 분포 전체가 아니라 tail class / tail index에 의해 좌우될 수 있다는 EVT 관점**이다.

KRA3의 핵심 사건은

\[
D\ge 9999.9
\]

라는 high-threshold exceedance이다. 따라서 질문을

> “9999.9를 몇 배로 채울까?”

보다

> “높은 threshold `u`를 넘었다는 조건에서 `D/u`의 초과분포가 threshold에 대해 안정적인가?”

로 바꾸는 것이 더 자연스럽다.

### 평가 항목

- `u=3000,5000,7000`에서 exceedance distribution의 형태가 안정적인가
- generalized Pareto shape parameter가 threshold 증가에 따라 안정되는가
- threshold stability plot에서 9999.9까지의 외삽이 정당화되는가

### 채택 기준

EVT 기반 모형이 pseudo-censoring에서 높은 threshold의 conditional quantile / exceedance probability를 안정적으로 재현할 때만 실제 상한 내부 분포에 사용한다.

---

# 4. Gabaix (1999): Zipf’s Law for Cities

**문헌**

Xavier Gabaix, “Zipf’s Law for Cities: An Explanation,” *Quarterly Journal of Economics* 114(3), 1999, 739–767.

- DOI: https://doi.org/10.1162/003355399556133

### KRA3에서의 역할

도시모형 자체가 아니라 **서로 다른 단위의 크기분포를 정규화하면 공통 rank-size 구조가 나타나는가**라는 발상을 사용한다.

경주 `r`에서 고배당을 정렬하여

\[
D_{r,(1)}\ge D_{r,(2)}\ge\cdots
\]

로 두고, 예를 들어 threshold 또는 경주별 scale로 정규화한

\[
D_{r,(j)}/u
\]

곡선이 출전두수·매출규모가 다른 경주에서도 비슷한지 본다.

### 통과 기준

- 경주별 정상화 후 rank-size curves가 일정한 family로 collapse
- tail exponent의 경주 간 분산이 설명 가능한 수준
- field size / turnover strata에서도 같은 방향

### 실패 시 의미

경주마다 tail 형태 자체가 크게 다르면 하나의 전역 power-law tail로 `9999.9`를 복원하는 설계는 폐기해야 한다. 이 경우 cluster/class-specific tail 또는 완전 비모수 복원이 필요하다.

---

# 5. Gabaix et al. (2003): 금융시장 power-law 배경

**문헌**

Xavier Gabaix, Parameswaran Gopikrishnan, Vasiliki Plerou, and H. Eugene Stanley, “A Theory of Power-Law Distributions in Financial Market Fluctuations,” *Nature* 423, 2003, 267–270.

- Gabaix 연구목록: https://pages.stern.nyu.edu/~xgabaix/research.html

### KRA3에서의 역할

직접 복원공식을 제공하지 않는다. 거래량과 가격변동의 극단값이 scaling relation을 가질 수 있다는 경제·금융 배경문헌으로만 사용한다.

KRA3에서는 삼쌍승 총매출/마권밀도와 배당 tail exponent의 관계를 탐색할 때 참고한다.

### 주의

금융시장 return/volume power law와 경마 pari-mutuel payout distribution을 동일한 생성과정으로 취급하지 않는다.

---

# 행동경제학 관련 Gabaix 문헌의 위치

Gabaix는 bounded rationality와 sparse attention 연구도 많지만, 이를 바로 “longshot 확률 과대가중”의 이론으로 쓰지 않는다. KRA3의 FLB 메커니즘 문헌은 probability weighting / lottery demand / horse-racing FLB 문헌에서 별도로 찾는다.

Gabaix 계열은 현재 프로젝트에서 우선적으로 **꼬리분포와 극단값을 어떻게 측정하고 검증할 것인가**에 사용한다.

---

# 평가 순서와 상태

| 단계 | 질문 | 상태 | 채택 기준 |
|---|---|---|---|
| 1 | Rank−1/2 tail exponent가 threshold·연도에 안정적인가? | **다음 분석** | 안정성 + 시간외 exceedance 예측 |
| 2 | power law가 다른 tail family보다 실제로 나은가? | 대기 | OOS predictive score 우세 |
| 3 | EVT/GPD threshold stability가 있는가? | 대기 | shape/quantile 안정성 |
| 4 | 경주별 정규화 rank-size curve가 collapse하는가? | 대기 | strata 간 공통형태 |
| 5 | turnover/field size가 tail exponent를 설명하는가? | 대기 | 반복 가능한 구조 |
| 6 | 통과한 tail model을 pseudo-censoring 복원에 결합 | 대기 | 실제 숨긴 배당/마권 복원 개선 |
| 7 | cross-pool signal과 tail prior를 결합 | 대기 | 2025 OOS + 실제 capped winner 개선 |

---

# KRA3에서 최종적으로 원하는 구조

만약 1–4가 통과한다면 복원은 다음처럼 역할을 분리한다.

1. **회계/매출 제약**: 가능한 총 마권질량과 개별 정수범위를 제한
2. **Gabaix/EVT tail model**: 상한 내부에서 어떤 배당/마권 크기 분포가 plausible한지 제한
3. **다른 승식 정보**: 그 tail 질량이 어느 삼쌍승 조합에 더 많이 배정될지 상대순위를 보조
4. **pseudo-censoring**: 위 결합이 실제 미검열 진실을 얼마나 복원하는지 검증
5. **FLB 분석**: 복원모형에 의존하지 않는 집합수준 결과를 주결론으로 유지하고, 검증을 통과한 경우에만 `9999.9` 내부 세부 FLB를 보조결과로 제시

현재까지의 실제 capped-winner 검증에서는 cross-pool 점복원이 균등배분보다 확실히 우월하지 않았다. 따라서 Gabaix/EVT tail 정보가 추가되더라도 **검증 전에는 점복원치를 주결론에 사용하지 않는다.**
