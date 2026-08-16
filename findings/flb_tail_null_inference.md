# 극단 `9999.9` 꼬리: null-referenced rare-event 추론

## 판정

Claude review가 지적한 대로 관측 날짜를 재표집한 empirical cluster bootstrap만으로 rare-event null을 검정하지 않는다.

다음 세 가지 **단측 방향검정**을 병기한다.

1. race-independent exact Poisson-binomial lower-tail
2. date-cluster sandwich normal score test
3. date-cluster null-centered Rademacher multiplier score bootstrap

강건한 5% 방향기각은 세 p값이 모두 0.05 아래일 때만 인정한다.

이 규칙에서 **2022–2025 pooled 표본은 residual_min/mid/max 세 시나리오 모두 강건한 방향기각**이다. 반면 **2025 단독 표본은 세 시나리오 모두 강건기각이 아니다.**

## 2022–2025 pooled

| 시나리오 | 실제 O | 기대 E | O/E | exact PB p | cluster p | wild-cluster p | 보수적 max p | 5% 강건기각 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| residual_min | 43 | 55.282 | 0.778 | **0.0368** | **0.0340** | **0.0348** | **0.0368** | 예 |
| residual_mid | 43 | 59.363 | 0.724 | **0.0090** | **0.0075** | **0.0079** | **0.0090** | 예 |
| residual_max | 43 | 63.444 | 0.678 | **0.0018** | **0.0012** | **0.0015** | **0.0018** | 예 |

따라서 pooled 표본에서 extreme-longshot capped set의 실제 적중빈도가 사전 마권질량보다 낮다는 방향은 추론방법 하나에만 의존하지 않는다.

## 2025 단독

| 시나리오 | O | E | O/E | exact PB p | cluster p | wild p | 강건기각 |
|---|---:|---:|---:|---:|---:|---:|---|
| min | 8 | 12.204 | 0.656 | 0.1458 | 0.1066 | 0.1088 | 아니오 |
| mid | 8 | 13.192 | 0.606 | 0.0988 | 0.0621 | 0.0640 | 아니오 |
| max | 8 | 14.181 | 0.564 | 0.0680 | 0.0336 | 0.0347 | 아니오 |

residual_max에서 cluster 계열은 5% 아래지만 exact Poisson-binomial이 0.068이므로 사전 규칙상 강건기각으로 부르지 않는다.

따라서 **2025 하나만으로 extreme-tail calibration deficit을 독립확정했다고 쓰지 않는다.**

## 2022–2024 복제구간

- residual_min: exact p 0.0843 → 강건기각 아님
- residual_mid: exact p 0.0276, cluster/wild 약 0.028 → 강건기각
- residual_max: exact p 0.0072, cluster/wild 약 0.0075 → 강건기각

## 기존 두-sided Poisson-binomial 수치와의 관계

기존 robustness report의 residual_min pooled 양측 tail p=0.1020과 여기의 단측 lower-tail p=0.0368은 단순히 2배 관계가 아니다. 기존 양측 통계는 discrete Poisson-binomial에서 양쪽 tail을 특정 규칙으로 합산한 값이며, 이번 분석은 연구질문에 맞춰 사전에 명시한 **방향가설 `O<E`의 lower-tail probability**를 직접 계산한다.

따라서 양측 수치를 오류라고 취급하지 않고, 질문이 다른 두 검정을 구분해 보고한다.

## 해석경계

이 방향은 전통적 favourite–longshot bias의 longshot-overbetting 방향과 일치하지만, 본 브랜치의 분석은 사후 exploratory extension이다.

가장 정확한 1차 표현은

> “2022–2025 pooled 자료에서 `9999.9` extreme-longshot 집합의 실현빈도는 그 집합의 사전 마권질량보다 낮으며, 이 방향은 회계적 residual 하한에서도 exact Poisson-binomial·날짜-cluster score·null-centered multiplier 검정 모두에서 5% 수준으로 유지된다.”

이다.

이 결과만으로 투자자의 선호·확률가중 메커니즘을 인과적으로 식별한다고 쓰지 않는다.
