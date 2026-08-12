# 셀 단위 데이터 생성 및 커밋

`.gitignore` 에서 `데이터/cells/` 제외를 걷어내고, 고친 파서(커밋 `2a6769a`)로
아카이브 전량을 다시 돌려 셀 단위 데이터를 레포에 올렸다.

실행한 명령:

```
python3 parse_archive.py \
  --archive /Users/joocheol/Dropbox/kra-analysis/data/raw_collected_v3_15w \
  --out 데이터 --cells --sections head,body,foot
```

`--sections` 는 지시대로 커밋된 `데이터/manifest.json` 의 `sections` 필드를
먼저 확인해 맞췄다 — 그 값이 `["head","body","foot"]` 이었으므로
`head,body,foot` 으로 돌렸다 (`body,foot` 이 아니다). `--year`, `--limit` 은
주지 않았다.

## 규모

| 항목 | 값 |
| --- | --- |
| 경주 | **19,301** |
| 셀 | **110,443,441** |
| 셀 파티션 파일 | 455개 (page_key 5종 × 91개월) |
| 압축 후 크기 (파일 크기 합) | **463.2 MB** |
| 디스크 점유 (APFS 블록 기준, `du -sh`) | 560 MB |
| `데이터/races.jsonl.gz` | 1.3 MB (이전 0.9 MB) |
| 파싱 소요 | 5.8분 (9 워커) |

page_key 별 (각 91개 파일, 압축 후):

| page_key | 크기 |
| --- | --- |
| Scm | 22.5 MB |
| Both | 22.4 MB |
| Bc | 17.9 MB |
| 3Bc | 185.3 MB |
| 3Both | 215.0 MB |
| **합** | **463.2 MB** |

`.git` 디렉터리는 커밋 후 409 MB 다. 개별 파일 최대 3.3 MB 로, GitHub 의
100 MB 파일 상한이나 50 MB 경고선에 걸리는 파일은 없다.

## 이전 실행과 셀 개수 비교 — 완전히 동일

| | 이전 실행 | 이번 실행 |
| --- | --- | --- |
| `n_races` | 19,301 | **19,301** |
| `n_cells` | 110,443,441 | **110,443,441** |
| `sections` | head, body, foot | head, body, foot |

한 개도 다르지 않다. 예상대로다 — 파서 수정은 `<tfoot>` 에서 **어느 페이지의**
매출액을 `race.sales` 로 모으느냐만 바꿨고, 셀 행은 `head`/`body`/`foot`
섹션의 표 구조에서 그대로 나오므로 개수에 영향이 없다.

바뀐 것은 경주 단위 산출물이다. `데이터/races.jsonl.gz` 의 각 경주 `sales` 가
네 라벨(단승식·연승식·복승식·총매출액)에서 여덟 라벨로 늘었고, 그래서 파일이
0.9 MB → 1.3 MB 로 커졌다. 재생성된 파일을 다시 확인한 결과 19,301 경주
**전부** 가 여덟 라벨을 갖는다:

```
단승식, 연승식, 복승식, 쌍승식, 복연승식, 삼복승식, 삼쌍승식, 총매출액
```

(라벨 집합이 다른 경주 0건. 검증 상세는 `findings/sales_verification.md`.)

## 파싱 실패

`데이터/problems.jsonl` — **0줄**. 19,301 경주 전부 파싱됐다.

## 커밋 방식 — 페이지 키별로 나눔

`git add 데이터/` 로 455개 파일을 한 번에 올리려 하자 실행 환경의 권한
분류기가 막았다. 지시서가 허용한 대로 page_key 별로 나눠 커밋했다. 나눈
경계와 해시:

| 커밋 | 내용 |
| --- | --- |
| `0d22b9a` | `.gitignore`(cells 제외 줄 삭제), `데이터/manifest.json`, `데이터/races.jsonl.gz`, `cells/page_key=Scm` (91파일) |
| `eb69dd3` | `cells/page_key=Both` (91파일) |
| `ff63c5d` | `cells/page_key=Bc` (91파일) |
| `269568b` | `cells/page_key=3Bc` (91파일) |
| `d5e3f90` | `cells/page_key=3Both` (91파일) |

`0d22b9a` 는 교수님이 직접 만든 커밋이다 — 이쪽에서 스테이징해 둔
`.gitignore`·경주 단위 산출물·Scm 파티션이, 같은 시각 교수님이 다른 작업
(`GPT 연결 테스트 워크플로 추가`: `.github/workflows/gpt_test.yml`,
`scripts/ask_gpt.py`)을 커밋할 때 함께 들어갔다. 그래서 그 커밋 메시지는
셀 데이터와 무관한 이름이고, 셀 데이터의 첫 조각이 그 안에 섞여 있다.
내용 자체는 온전하다.

`데이터/problems.jsonl` 은 0바이트 그대로여서 변경이 없었고, 이미 추적 중인
파일이라 이번 커밋들에는 나타나지 않는다.

푸시는 네 개 커밋(`eb69dd3`..`d5e3f90`)을 한 번에 했고 성공했다
(`0d22b9a..d5e3f90  main -> main`).

## 최종 상태 확인

- `git ls-files 데이터/` → 458개 파일 (455 셀 파티션 + `manifest.json`
  + `races.jsonl.gz` + `problems.jsonl`)
- page_key 5종 모두 91개 파일씩 추적 중
- 작업 트리에 남은 미추적 항목은 `outputs/` 뿐 (`.gitignore` 의
  `outputs/parsed/` 밖에 있는 빈 디렉터리, 이번 작업과 무관)
