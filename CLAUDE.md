# 지금 할 일 — 딱 하나

셀 단위 배당률 데이터를 아카이브 전체에서 만들어 레포에 커밋한다. 지금까지는
`.gitignore`가 `데이터/cells/`를 명시적으로 뺐다("파싱 산출물의 셀 파티션은
560MB 다. 레포에 넣지 않는다"). 이번에는 교수님이 직접 넣으라고 지시했다 —
이후 분석(절단 배당 복원)이 셀 단위 데이터를 필요로 하는데, 그게 레포에
있어야 클라우드 Claude Code 로도 분석을 넘길 수 있기 때문이다.

또한 지금 `데이터/races.jsonl.gz`, `데이터/manifest.json`은 매출액 수집이
Scm 페이지 하나만 보던 옛 `kra/race.py` (버그: 일곱 승식 중 넷만 잡음) 로
만들어진 것이다. 이번에 전량을 다시 돌리면 고친 파서(커밋 `2a6769a`, 검증은
`findings/sales_verification.md`)로 자동 재생성된다.

**이 파일에서 하는 일은 이것뿐이다.** 셀 데이터를 만들고 커밋·푸시하고
결과를 보고한다. 분석(절단 셀의 K, N 계산 등)은 다음 단계이고 여기서 하지
않는다.

## 절차

0. `git pull --ff-only` 로 이 지시서 자체가 최신인지 받는다.

1. `.gitignore` 에서 `데이터/cells/` 줄을 지운다. 그 줄의 주석("파싱 산출물의
   셀 파티션은 560MB 다. 레포에 넣지 않는다")도 함께 지운다 — 더 이상 맞는
   말이 아니다.

2. `parse_archive.py` 를 아카이브 전체에 돌린다. `--year`, `--limit` 은 주지
   않는다 (전량).

   ```
   python3 parse_archive.py \
     --archive ~/Dropbox/kra-analysis/data/raw_collected_v3_15w \
     --out 데이터 --cells --sections body,foot
   ```

   기존 `데이터/manifest.json` 의 `sections` 가 `["head","body","foot"]` 가
   아니라 `["body","foot"]` 로 보이면 그쪽 값을 맞춘다 — 실제로 커밋된
   `데이터/manifest.json` 을 열어 `sections` 필드를 먼저 확인하고, 있으면
   그 값을, 없으면 `body,foot` 을 그대로 쓴다.

3. 완료 후 `데이터/races.jsonl.gz`, `데이터/manifest.json`,
   `데이터/problems.jsonl`, `데이터/cells/` 전체를 커밋한다.

   ```
   git add .gitignore 데이터/
   git commit -m "셀 단위 데이터 생성 및 커밋 (파서 수정 반영)"
   git push
   ```

   커밋이 하나로 너무 크면(예: git이 경고하거나 push 가 실패하면) 페이지
   키별로 나눠 커밋해도 된다 — 어떻게 나눴는지 보고에 적는다.

4. 확인한다.
   - `du -sh 데이터/cells` 로 실제 크기
   - `데이터/manifest.json` 의 `n_races`, `n_cells` 가 이전 실행(19,301 경주,
     110,443,441 셀)과 비교해 얼마나 다른지 — 파서 수정이 셀 개수 자체에는
     영향이 없어야 하므로(매출액은 `<tfoot>`, 셀은 `body`/`foot` 구조에서
     나옴) 다르면 그 이유를 짚는다.
   - `git log -1` 로 최종 커밋 해시

## 결과를 남기는 방법 — 반드시 이렇게

1. `findings/cells_committed.md` 파일을 만든다. 담을 내용:
   - 전체 경주 수, 전체 셀 수, 디스크 크기(압축 후)
   - 커밋 방식(한 번에 했는지 나눴는지)과 최종 커밋 해시(들)
   - 이전 실행과 셀 개수가 같은지 다른지, 다르면 원인
   - `데이터/problems.jsonl` 에 몇 줄이 있는지 (파싱 실패 기록)
2. `git add findings/cells_committed.md && git commit -m "셀 데이터 커밋 보고" && git push`
3. `git log -1` 로 확인하고 커밋 해시를 마지막 줄에 출력한다.

## 하지 않는 것

- 절단 셀(9999.9)의 K, N 계산이나 다른 분석을 하지 않는다 — 다음 단계다
- `kra/race.py`, `kra/htmltable.py`, `parse_archive.py` 를 고치지 않는다
- `findings/cells_committed.md` 외에 다른 파일을 만들지 않는다
- P0/P1/P2 같은 이름을 쓰지 않는다
