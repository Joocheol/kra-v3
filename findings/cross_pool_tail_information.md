# 다른 승식 정보를 이용한 삼쌍승 `9999.9` 꼬리 복원 가능성

## 목적

2018-07-01 비상한 삼쌍승 자료에서 고배당 꼬리의 경험적 순위분포가 경주 간에 상당히 안정적이라는 결과가 확인되었다. 다음 질문은 같은 경주의 다른 승식 정보가 삼쌍승 `9999.9` 꼬리 복원에 추가적인 설명력 또는 제약을 제공할 수 있는가이다.

이 문서는 현재까지의 분석적 판단과 다음 검증 설계를 기록한다. **아직 같은 날의 다른 승식 셀 단위 대응 그림을 완성한 결과 보고서는 아니다.** 따라서 아래 내용은 사전 가설·검증 계획으로 취급한다.

## 현재 판단

다른 승식 정보는 유망하다. 다만 삼쌍승 경험적 꼬리분포를 대체하는 독립 모형이라기보다, 다음 세 역할 중 하나로 쓰는 것이 자연스럽다.

1. **꼬리 형태 선택**: 어떤 비상한 삼쌍승 꼬리 템플릿을 적용할지 선택하는 보조정보.
2. **꼬리 경사 예측**: 삼쌍승 고배당 꼬리의 steepness 또는 tail mass를 예측하는 설명변수.
3. **구조적 제약**: 다른 승식과 지나치게 모순되는 삼쌍승 복원값을 배제하는 정합성 제약.

우선순위는 다음처럼 본다.

> 삼복승식 > 쌍승식 ≈ 복승식 > 단승식

이는 정보가 없다는 뜻이 아니라, 삼쌍승 상태공간에 얼마나 직접적으로 대응하는가에 따른 우선순위다.

## 승식별 예상 역할

### 1. 삼복승식

가장 우선적으로 검토한다. 삼복승식은 순서를 무시한 세 말 집합이고, 삼쌍승식은 같은 세 말에 순서를 추가한 상태공간이다. 따라서 삼복승은 다음을 직접 알려줄 가능성이 크다.

- 어떤 세 말 집합이 상대적으로 많이/적게 팔리는가
- 고배당 triple 집합의 질량이 얼마나 두꺼운가
- 삼쌍승 꼬리의 전체 위치와 밀도
- 같은 세 말 집합 내부의 order split을 추정할 때 필요한 기준 질량

향후에는 각 unordered triple의 삼복승 상대질량과 그 triple에 속한 6개 ordered trifecta 셀의 총질량·내부 분할을 연결하는 그림과 통계를 우선 계산한다.

### 2. 쌍승식

쌍승식은 순서 있는 두 말 조합이므로 삼쌍승 `(1착, 2착, 3착)`의 앞 두 위치 구조와 직접 연결된다.

예상 활용은 다음과 같다.

- 1-2착 prefix의 인기 집중도 측정
- 삼쌍승 꼬리에서 특정 prefix가 차지할 총질량의 보조 예측
- 삼쌍승 내부 assignment score 개선
- 순서효과가 큰 경주와 작은 경주의 구분

### 3. 복승식

복승식은 순서 없는 말쌍의 선호를 제공한다. 쌍승보다 정보는 거칠지만 경주 내 pair structure와 전반적 집중도를 측정하는 데 쓸 수 있다.

### 4. 단승식

단승식은 개별 말의 인기/강도 정보를 제공한다. 삼쌍승 꼬리의 세부 조합 배분을 직접 식별하지는 못하지만, 다음과 같은 경주 수준 특징을 만들 수 있다.

- HHI 또는 entropy
- 1위 인기마 질량
- 상위 2~3두 집중도
- 인기분포의 rank slope

이 특징들은 경주가 전체적으로 concentrated한지 diffuse한지를 예측하는 보조변수로 사용할 수 있다.

## 권장 그림

같은 2018-07-01 비상한 표본을 이용해 아래 그림을 순서대로 만든다.

1. **승식별 normalized rank-profile overlay**
   - 단승, 복승, 쌍승, 삼복승, 삼쌍승을 각각 경주 내 평균으로 정규화
   - 조합 수가 다르므로 rank percentile 축 사용
   - 각 승식의 중앙곡선과 IQR 비교

2. **승식별 tail-only rank profiles**
   - 각 승식에서 상위 고배당 꼬리를 percentile 또는 승식별 threshold로 정의
   - 삼쌍승의 `>5000, >6000, ..., >9000`와 대응되는 tail mass 기준도 병행 검토

3. **Cross-pool tail steepness scatter**
   - x축: 다른 승식의 tail steepness (`p10/p90`, log-slope 등)
   - y축: 같은 경주의 삼쌍승 tail steepness
   - 상관과 비선형 관계 확인

4. **Concentration heatmap / correlation matrix**
   - entropy, HHI, p10/p90, p50, tail fraction 등을 승식별로 계산
   - 동일 경주에서 어떤 특징이 함께 움직이는지 확인

5. **삼복승 triple mass vs trifecta six-order mass**
   - unordered triple별 삼복승 `1/odds`와 해당 6개 삼쌍승 ordered 셀의 합을 비교
   - 이것이 강하면 삼복승을 삼쌍승 복원의 구조적 anchor로 직접 사용할 근거가 생긴다.

6. **쌍승 prefix mass vs trifecta prefix mass**
   - ordered pair `(a,b)` 쌍승 `1/odds`와 `(a,b,*)` 삼쌍승 질량 합 비교
   - prefix-level anchor 가능성 검토

## 통계 검증

그림만으로 채택하지 않는다. 아래 순서로 검증한다.

### A. 설명력

경주별 삼쌍승 tail characteristic을 목표변수로 두고 다른 승식 특징의 설명력을 측정한다.

예시 목표변수:

- 삼쌍승 tail `p10/p90`
- 삼쌍승 tail log-rank slope
- tail fraction
- empirical profile distance

### B. 시간외 검증

가능하면 2022--2024에서 규칙을 선택하고 2025를 holdout으로 유지한다. 2025 결과를 보고 변수·가중치를 다시 조정하지 않는다.

### C. 실제 복원 성능

동일한 accounting lower/upper bounds 아래에서 비교한다.

- uniform
- empirical trifecta rank profile
- shifted power law
- empirical trifecta rank profile + cross-pool information

평가지표:

- cell-weighted MAE
- race-weighted MAE
- rank MAE
- date-cluster paired bootstrap CI

특히 near-tail validation에서는 **모든 방법에 동일한 hidden lower/upper information을 제공**해야 한다.

## 현재 가장 유망한 구조

현재 단계에서 가장 자연스러운 후보는 다음과 같다.

> **삼쌍승 경험적 rank profile을 기본 tail shape으로 두고, 삼복승·쌍승 정보를 이용해 triple/prefix 수준의 질량을 anchor한 뒤, 그 내부에서 경험적 rank shape으로 배분한다.**

즉 다른 승식을 이용해 삼쌍승 꼬리 전체를 새로 예측하기보다,

- 삼복승은 **3두 집합 수준 질량**,
- 쌍승은 **1-2착 prefix 수준 질량**,
- 단승은 **말별 주변 인기**,
- 삼쌍승 경험적 rank profile은 **최종 미세 꼬리 모양**

을 담당하게 하는 계층적 구조다.

이 접근은 cross-pool 정보를 단순한 black-box predictor로 사용하는 것보다 해석 가능성이 높고, 기존 KRA3의 회계적 부분식별과도 잘 결합된다.

## 주의사항

1. 다른 승식과 삼쌍승의 높은 정합성이 곧 실제 `9999.9` 셀의 정답 식별을 의미하지 않는다.
2. 실제 capped 셀의 true ticket count를 대규모로 관측하지 못하므로 near-tail masking은 여전히 간접 검증이다.
3. 다른 승식 정보를 추가할 때도 target 삼쌍승 hidden cells에서 정보를 누출해서는 안 된다.
4. 2018 구제도에서는 2022+ 회계식을 그대로 적용하지 않는다. 형태 비교에는 경주 내 `1/odds` 정규화를 사용하고, 절대 마권수 연결은 제도 차이를 별도로 처리한다.
5. 다른 승식 정보가 성능을 개선하지 않으면 복잡성을 추가하지 않는다.

## 다음 실행 순서

1. 2018-07-01의 `Scm`, `Both`, `Bc`, `3Bc`, `3Both` 셀을 같은 경주 ID로 결합한다.
2. 승식별 normalized rank profile과 tail profile 그림을 만든다.
3. 삼복승 triple ↔ 삼쌍승 six-order mass, 쌍승 prefix ↔ 삼쌍승 prefix mass를 직접 비교한다.
4. 경주 수준 cross-pool 특징과 삼쌍승 tail steepness 관계를 수치화한다.
5. 유망한 관계만 2022--2024 학습 / 2025 holdout 복원 검증으로 넘긴다.

현재 판정은 **"cross-pool information is promising, especially trio and exacta, but not yet validated as an improvement over the empirical trifecta tail profile."** 이다.
