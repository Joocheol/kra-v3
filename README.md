# KRA 배당 상한 복원

한국마사회(KRA) 파리뮤추얼 배당판에서 `9999.9`로 상한 코딩된 조합의 잠재
100원 마권 수를 복원하는 연구 저장소다. `9999.9`는 실제 초고배당뿐 아니라
무투표(`n=0`)도 나타낼 수 있으므로, 배당을 연속변수로 외삽하지 않고 총합이
고정된 잠재 정수 빈도표로 다룬다.

## 현재까지 확인된 사실

- 19,301경주, 삼쌍승식 검열 셀 3,774,486개
- 동결한 KRA 상세 성적표 143개에서 상한 초과 지급 144건 확인
  (삼쌍승 142건, 삼복승 2건)
- 2022--2025년 주표본의 무투표 합계 구간: **0--705,764개**
  (7,546경주 모두 하한 0)
- 전기간 진단표본의 엄격 구간: 182--1,633,769개
  (검열 셀의 0.006%--51.636%)
- 양의 하한 182개는 비정상적으로 낮은 매출을 보인 2017년 서울 두 경주에만
  의존하며, 주표본 결과나 대표 추정치로 사용하지 않음
- 불일치 셀을 `[1,T]`로 두는 182--2,244,248개 최악경계는 제외 셀 수를
  기계적으로 더한 값이라 동등한 강건성 추정치로 사용하지 않음
- 2016--2019년의 반올림 불일치 2,239경주는 최종 삼쌍승 총마권보다 1% 또는
  5% 이른 **단일** 스냅샷으로 모든 미검열 셀을 설명할 수 있는 경우가 0건

원자료에는 2020·2021년 파티션이 없다. 2016--2019년에는 최종 매출과 양립하지
않는 미검열 셀이 있지만 2022--2025년에는 없으므로, 후속 확률모형과 설명력
분석은 2022--2025년만 주표본으로 쓴다. 2016--2019년의 2,239개 불일치는
단순한 1--5% 이내의 가까운 배당판 스냅샷 시점 차이로도 해소되지 않았다.
따라서 이전 시기는 원인이 해명되지 않은 역사적 진단표본이며 강건성 증거로
사용하지 않는다.

## 실질 분석 결과

2022--2024년으로 모형을 선택하고 2025년을 시간외 평가한 가상 상한 실험에서는
3,000·5,000배의 일부 비균등 모형이 균등보다 나았지만 7,000배의 차이는 작고
모형별 방향도 일치하지 않았다. 이 원표본은 실제 상한 대상보다 격자가 작고
셀당 마권이 훨씬 많아 지원집합이 다르다. 따라서 실제 상한 셀의 균등배분은
검증으로 선택된 최적모형이 아니라 최소 대칭 기준선이다. 대칭 다항과
Dirichlet--multinomial의 기대 무투표가 거의 0인 결과도 지원집합 밖 기능형식
외삽이므로 구조적 0의 추정이나 주결과로 사용하지 않는다.

삼쌍승 복원표를 하위 승식으로 주변화한 2025년 가격 정합성 `R²`는 균등배분
조건에서 단승 0.96543, 쌍승 0.97050, 복승 0.95936, 삼복승 0.97981이다.
검열 잔여총량의 회계적 하한·중간값·상한에 따른 변화는 0.0005 이내였지만,
이는 배분규칙을 고정한 민감도다. 비균등 배분과 2·3착 축 반전 결과도 보고서에
병기한다. 위치별 비균등 배분(`beta=0.10`)은 거의 같은 결과였지만, 2·3착 축을
뒤집으면 쌍승 `R²`가 0.83919, 복승은 0.87469로 크게 낮아져 파싱한 축 방향을
내부적으로 지지했다. 이 수치는 풀 사이의 내부 가격 정합성이다.

### 2025년 실제 착순 평가

가격 정합성과 별개로, 2025년 2,426경주의 실제 1·2·3착 순서조합을 사후 채점했다.
삼쌍승 상태분포는 착순을 보기 전에 배당판과 해당 풀 총매출만으로 완성한다.

- 삼쌍승 균등완성 평균 Brier: **0.9916302**
- 단승 Harville 평균 Brier: **0.9926153**
- 평균 차이 `trifecta_uniform - win_harville`: **-0.00098517**
  - 날짜 cluster bootstrap 95%: **[-0.00135358, -0.00058067]**
- 2·3착 축을 뒤집으면 평균 Brier가 **0.9927140**으로 악화
  - `swapped_23 - uniform`: **0.00108387**
  - 날짜 cluster bootstrap 95%: **[0.00056428, 0.00161204]**
- 실현 상태의 예측순위 중앙값: 삼쌍승 7.083%, Harville 7.645%
- 실현 상태 상위 10%: 삼쌍승 1,417/2,426, Harville 1,383/2,426
- 상한 잔여총량 하한·중간·상한의 평균 Brier: 0.9916293 / 0.9916302 / 0.9916311
- 실현된 삼쌍승 조합 자체가 `9999.9`였던 경주는 8건이며, 8건 모두 사전
  회계적 확률하한은 0이다. 확률상한 중앙값은 0.0000729다.

따라서 삼쌍승 가격에는 단승 가격을 Harville로 순차확장한 것보다 실제 상위 세
착순과 더 잘 정렬되는 정보가 들어 있다. 2·3착 축 반전이 실제 착순에서도
악화된다는 결과는 페이지 방향성에 대한 외부 반증검사이기도 하다. 다만 이는
정규화한 시장가격을 확률예측처럼 채점한 결과이며, 시장효율성·객관적 확률의
정확성·인과효과를 뜻하지 않는다.

### Claude 1차 검토 후 강건성 분석

최초 2025 설계와 수치를 커밋으로 고정한 뒤 별도의 사후 강건성 분석을 수행했다.
2022--2024 착순으로만 discounted-Harville의 조건부 할인모수
`lambda=0.740`을 적합하고 이를 고정해 2025년에 적용했다.

- 2025 삼쌍승 균등완성 Brier: **0.9916302**
- 2025 discounted-Harville Brier: **0.9922405**
- 평균 차이: **-0.00061027**
  - 날짜 cluster bootstrap 95%: **[-0.00098080, -0.00023560]**
- 2022--2024년 7,245경주 retrospective replication:
  삼쌍승 - 일반 Harville **-0.00085216**
  (95% **[-0.00107847, -0.00060932]**)
- `residual_mid`를 고정하고 허용되는 모든 상한셀 정수배분을 극단화한
  2025 평균 Brier 범위: **0.9916300--0.9916306**

실제 적중조합이 `9999.9`였던 2025년 8경주는 동결 KRA 지급표와 전부 연결됐다.
지급식 마권 수는 8/8건에서 점식별됐고 균등완성 배정의 평균 절대오차는
59.344장이었다. 이는 당첨된 상한셀만 관측되는 선택표본이므로 전체 상한셀의
대표 정확도로 해석하지 않는다. 자세한 결과는
`findings/outcome_robustness.md`에 있으며, 전체 경주별 결과도
`데이터/outcome_robustness.csv.gz`로 동결한다.

교차시장 단계가 사용하는 원시 격자도 별도 전수검사했다. 2022--2025년 9,671개
경주의 19,827,297개 숫자 행을 읽었고, 동일값 중복 2,823,966행은 있었지만
서로 다른 값의 충돌 중복과 숫자 spanned 셀은 각각 0건이었다. 단승·복승·쌍승·
삼복승·삼쌍승의 활성마 조합 support도 전 경주에서 이론값과 정확히 일치했다.
이는 현재 표본에서 기존 dictionary 로더가 중복·병합·누락으로 가격표를 조용히
바꾸는 경로를 차단한다.

자세한 결과는 다음 보고서에 있다.

- `findings/winning_capped_payouts.md`
- `findings/trifecta_feasible_sets.md`
- `findings/snapshot_timing.md`
- `findings/masked_reconstruction.md`
- `findings/sparse_multinomial_baseline.md`
- `findings/dirichlet_multinomial.md`
- `findings/cross_market_reconstruction.md`
- `findings/cross_market_input_validation.md`
- `findings/outcome_evaluation.md`

## 재현

```bash
python3 -m pip install -r requirements-analysis.txt
python3 -m unittest discover -s tests -v
python3 analyze_feasible_sets.py
python3 collect_winning_payouts.py --offline
python3 analyze_masked_reconstruction.py
python3 analyze_sparse_baseline.py
python3 analyze_dirichlet_multinomial.py
python3 analyze_cross_market.py
python3 validate_cross_market_inputs.py
python3 diagnose_snapshot_mismatch.py
python3 analyze_outcome_evaluation.py
python3 analyze_outcome_robustness.py
git diff --exit-code -- \
  findings \
  데이터/outcome_robustness.csv.gz \
  데이터/dirichlet_multinomial_fit.csv \
  데이터/winning_payout_html.sha256
actual="$(gzip -cd 데이터/outcome_evaluation.csv.gz | sha256sum | awk '{print $1}')"
expected="$(tr -d '[:space:]' < 데이터/outcome_evaluation.sha256)"
test "$actual" = "$expected"
```

CI에서는 단위·속성·종단간 테스트, 입력검증, 스냅샷 진단, 2025년 착순평가와
검토 후 강건성 분석을 전수 실행한다. 착순평가 보고서와 강건성 보고서는
커밋본과 직접 비교하고, 두 압축 CSV도 압축을 푼 내용 단위로 대조한다.
최초 경주별 착순평가 16,982행의 SHA-256은
`c3bc666c1e67f45c3def697bb80b2f4467c37cb97a8d310ef42f5610d202512b`로 고정한다.

분석 원칙과 정보 분리는 `RESEARCH_PROTOCOL.md`를 따른다.

## Claude 독립 연구검토

PR에 `ai-review` 라벨을 붙이면 `.github/workflows/ai-review.yml`이 다음을
수행한다.

1. 라벨을 즉시 제거해 한 번의 검토 요청으로 소비한다.
2. 단위 테스트와 전수 분석을 다시 실행하고 커밋 산출물과 비교한다.
3. Claude가 식별, 정수 회계, 반올림, 표본선택, 정보누출, 검증설계,
   재현성을 독립적으로 비판한다.
4. 구조화된 심사보고서를 PR 코멘트로 남긴다.

검토 모델은 `claude-opus-5`로 고정한다. 한 PR에서 성공적으로 완료할 수 있는
검토는 최대 4회이며, 실패한 Actions 실행은 횟수에 포함하지 않는다. 지적을
반영한 새 커밋을 푸시한 뒤 `ai-review` 라벨을 다시 붙이면 다음 회차가
실행된다. 4회를 모두 마친 뒤에는 새 PR에서 다시 시작한다.

Claude는 파일을 수정하거나 PR을 자동 병합하지 않는다. 지적 반영 여부와
식별가정·표본규칙·실질적 주장 변경은 연구자가 결정한다.

저장소에는 Actions secret `CLAUDE_CODE_OAUTH_TOKEN`과 `ai-review` 라벨이 한
번 설정되어 있어야 한다.

```bash
gh auth status
gh secret list --repo Joocheol/kra-v3
gh label list --repo Joocheol/kra-v3 --search ai-review
```

시크릿 목록에 `CLAUDE_CODE_OAUTH_TOKEN`이 없거나 토큰을 갱신할 때만 다음을
실행한다. `claude setup-token`이 출력한 토큰을 복사해 `gh secret set`의
입력창에 붙여 넣는다. 토큰은 파일이나 셸 기록에 저장하지 않는다.

```bash
claude setup-token
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo Joocheol/kra-v3
gh label create ai-review \
  --repo Joocheol/kra-v3 \
  --color 5319E7 \
  --description "Claude 독립 연구검토 실행" \
  --force
```
