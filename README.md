# KRA 배당 상한 복원

한국마사회(KRA) 파리뮤추얼 배당판에서 `9999.9`로 상한 코딩된 조합의 잠재
100원 마권 수를 복원하는 연구 저장소다. `9999.9`는 실제 초고배당뿐 아니라
무투표(`n=0`)도 나타낼 수 있으므로, 배당을 연속변수로 외삽하지 않고 총합이
고정된 잠재 정수 빈도표로 다룬다.

## 현재까지 확인된 사실

- 19,301경주, 삼쌍승식 검열 셀 3,774,486개
- 동결한 KRA 상세 성적표 143개에서 상한 초과 지급 144건 확인
  (삼쌍승 142건, 삼복승 2건)
- 엄격 표본의 무투표 합계 구간: 182--1,633,769개
  (검열 셀의 0.006%--51.636%)
- 불일치 셀 완화 표본의 구간: 182--2,244,248개
  (0.005%--59.458%)
- 양의 하한 182개는 2017년 서울 두 경주에서만 총합제약이 결속된 사례 결과이며,
  표본 전체의 대표 추정치로 사용하지 않음

원자료에는 2020·2021년 파티션이 없다. 2016--2019년에는 최종 매출과 양립하지
않는 미검열 셀이 있지만 2022--2025년에는 없으므로, 후속 확률모형과 설명력
분석은 2022--2025년을 주표본으로 하고 2016--2019년을 별도 강건성 표본으로 둔다.

## 실질 분석 결과

2022--2024년으로 모형을 선택하고 2025년을 시간외 평가한 가상 상한 실험에서,
실제 상한에 가까운 7,000배 구간의 비균등 배분모형은 대부분 균등모형으로
수축했다. 실제 상한 셀에서 검열 잔여마권은 셀당 중앙값 191.66장이라 대칭
다항모형과 시간외 추정 Dirichlet--multinomial 모두 기대 무투표 셀을 사실상
0개로 예측한다. 이는 무투표가 없다는 증명이 아니다. 많은 무투표를 설명하려면
가상 상한에서 관측한 것보다 훨씬 강한 조합 이질성이나 구조적 0 과정이 필요하지만,
현재 자료만으로 둘을 식별할 수 없다는 뜻이다.

삼쌍승 복원표를 하위 승식으로 주변화한 2025년 가격 정합성 `R²`는 단승
0.96543, 쌍승 0.97050, 복승 0.95936, 삼복승 0.97981이다. 검열 잔여총량의
회계적 하한·중간값·상한을 바꿔도 각 `R²` 변화는 0.0005 이내였다. 이 수치는
풀 사이의 내부 가격 정합성이며, 실제 착순 예측력이나 시장효율성을 뜻하지 않는다.

자세한 결과는 다음 보고서에 있다.

- `findings/winning_capped_payouts.md`
- `findings/trifecta_feasible_sets.md`
- `findings/masked_reconstruction.md`
- `findings/sparse_multinomial_baseline.md`
- `findings/dirichlet_multinomial.md`
- `findings/cross_market_reconstruction.md`

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
git diff --exit-code -- \
  findings \
  데이터/dirichlet_multinomial_fit.csv \
  데이터/winning_payout_html.sha256
```

CI에서는 모든 압축 CSV를 풀어 커밋 산출물과 내용 단위로도 비교한다.

분석 원칙과 후속 모형의 정보 분리는 `RESEARCH_PROTOCOL.md`를 따른다.

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
