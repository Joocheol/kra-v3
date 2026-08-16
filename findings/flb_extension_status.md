# `9999.9` 복원 후 FLB 분석의 연구지위와 해석경계

## 연구지위

이 브랜치에서 추가한 favorite–longshot 관련 분석은 기존 2025 outcome proper-score 확인분석을 대체하는 사전등록 confirmatory test가 아니다.

`9999.9` 표시상한을 복원할 수 있는지 검토하는 과정에서

1. capped 집합 전체의 마권질량은 개별 배분 없이 식별 가능하고,
2. 그 집합의 실제 적중빈도도 관측 가능하다는 점이 드러나면서

추가된 **exploratory extension**이다.

따라서 새 결과의 p값이나 threshold 선택을 기존 확인분석과 같은 사전검정처럼 표현하지 않는다.

## 용어

가장 안전한 1차 표현은

> “극단 longshot 표시상한 집합에서 관측 적중빈도가 해당 집합의 사전 마권질량보다 낮다”

또는

> “extreme-longshot calibration deficit / overbetting-direction pattern”

이다.

`favorite–longshot bias (FLB)`라는 용어는 이 방향이 전통적인 FLB 문헌의 longshot overbetting과 일치한다는 **문헌적 연결**에 사용한다.

현재 자료만으로 다음을 직접 식별한다고 쓰지 않는다.

- 투자자의 확률가중 함수
- 선호·효용의 인과적 형태
- 비합리성의 원인
- 공제 후 수익기회의 존재
- 시장효율성 전체의 기각

## 통계적 주장 규칙

극단 capped-set 방향검정은 다음 세 추론을 병기한다.

1. race-independent exact Poisson-binomial null
2. date-cluster sandwich score test
3. date-cluster null-centered multiplier score bootstrap

5% 수준의 “강건한 방향기각”은 세 방법이 모두 같은 결론일 때만 사용한다.

특히 residual_min은 기존 exact Poisson-binomial에서 경계적이므로, 다른 방법 하나가 5% 아래라는 이유만으로 확정적 FLB 증거라고 부르지 않는다.

## 배당구간 O/E

10–100배, 300–3000배, `9999.9` 등 배당구간별 O/E는 사후 탐색적 패턴이다.

시장가격 자체로 구간을 나눈 데서 기계적 모양이 생기는지 확인하기 위해, 각 경주의 관측 마권질량을 null 확률로 고정한 calibration-null simulation을 별도로 수행한다.

따라서 현재의 “비단조 FLB” 표현도 null simulation과 연도별 강건성을 통과한 뒤에만 강한 서술로 승격한다.

## 복원과 substantive conclusion의 분리

주결론은 가능한 한 개별 `9999.9` allocation을 필요로 하지 않는 집합수준 결과로 유지한다.

복원모형은 극단꼬리 내부 해상도를 높이는 보조분석이다. 복원모형의 점예측이 실패해도 capped-set calibration 결과는 기계적으로 변하지 않는다.

반대로 세부 `9999.9` 내부 FLB는 allocation uncertainty를 전파한 다중대치/부분식별 분석이 검증된 뒤에만 보고한다.
