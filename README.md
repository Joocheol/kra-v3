# KRA 배당 상한 복원

한국마사회(KRA) 파리뮤추얼 배당판에서 `9999.9`로 상한 코딩된 조합의 잠재
100원 마권 수를 복원하는 연구 저장소다. `9999.9`는 실제 초고배당뿐 아니라
무투표(`n=0`)도 나타낼 수 있으므로, 배당을 연속변수로 외삽하지 않고 총합이
고정된 잠재 정수 빈도표로 다룬다.

## 현재까지 확인된 사실

- 19,301경주, 삼쌍승식 검열 셀 3,774,486개
- KRA 상세결과에서 실제 상한 초과 지급이 확인된 사례 142건
- 엄격한 반올림·총합 제약이 성립하는 검열 경주 13,884개
- 회계 제약만으로 최소 182개 무투표 셀이 확정되는 2개 경주

자세한 결과는 다음 두 보고서에 있다.

- `findings/winning_capped_payouts.md`
- `findings/trifecta_feasible_sets.md`

## 재현

```bash
python3 -m unittest discover -s tests -v
python3 analyze_feasible_sets.py
git diff --exit-code -- \
  findings/trifecta_feasible_sets.md \
  데이터/trifecta_feasible_sets.csv.gz
```

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
