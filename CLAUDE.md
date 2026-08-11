# kra-v3

KRA 원시 경주성적·배당 페이지를 L1 테이블로 파싱한다. 지금 할 일은 이것 하나다.

## 원칙

1. **파서는 읽기만 한다. 판정하지 않는다.** `9999.9`, `----`, `-`, 빈 칸 전부 원문 그대로 저장한다. 숫자 변환도 하지 않는다.
2. **파생 필드를 만들지 않는다.** 유효두수, 취소 여부, 상한 여부, 복승 지급 범위 — 전부 L2의 일이다. 여기서 만들면 나중에 근거를 못 댄다.
3. **이상한 값이 나오면 저장하고 넘어간다.** 멈추는 경우는 아래 게이트 하나뿐이다.

## 데이터

```
~/Dropbox/kra-analysis/data/raw_collected_v3_15w/kra_<YYYY>/raw_archive/<YYYY>/<YYYY-MM>/<race_id>.json.gz
```

iMac에서는 `~/Library/CloudStorage/Dropbox/...` 쪽이다. 둘 다 확인해서 있는 쪽을 쓴다.

`race_id` = `YYYY-MM-DD_<meet>_<rc_no>`, 예: `2018-01-05_3_01`. 전체 19,301경주.

**연도 디렉터리를 가정하지 마라.** 2016–2025 전 연도가 있지 않다. glob으로 실제 존재하는 것만 잡고, 어떤 연도가 있는지 첫 실행에서 출력해라.

### 파일 구조

gunzip → JSON. `json.loads(..., strict=False)`가 필요하다. 최상위 키 넷:

- `race_id` — str
- `meta` — dict. `real_rc_date` `race_date` `meet` `real_rc_no` `collector_version` `scm_gate` `expected_date_text` `base_page_checks` `base_pages_match` `has_arrival_order_text` `placeholder_9999_9_count` `raw_status` `collection_attempts` `retry_history`
- `pages` — dict, 키 5개
  - `Scm` `Both` `Bc` — HTML 문자열
  - `3Bc` `3Both` — dict. 키는 `_probe` + 출마번호 문자열(`'1'`, `'2'`, …). 그 번호는 URL의 `chulNo1` 값이다.
- `urls` — `pages`와 같은 구조

문자열은 수집기가 이미 유니코드로 디코드해 두었다. HTML 안에 `charset=euc-kr`이 적혀 있지만 **다시 디코드하지 마라.**

## 게이트 — 여기서만 멈춘다

각 HTML 문자열에 `<!doctype html`(대소문자 무시)과 `<table`이 **둘 다** 있어야 한다. 하나라도 없으면 그 경주를 건너뛰지 말고 **전체 실행을 중단**하고 `race_id`와 `page_key`를 출력해라.

이유: 중간 도구가 HTML을 조용히 텍스트로 바꿔놓은 사고가 실제로 있었다. 태그가 없는 것은 원본이 아니다. 조용히 넘어가면 빈 데이터셋이 정상으로 보인다.

## 산출물

### `outputs/l1/cells_<YYYY>.parquet` — 표 안의 모든 셀

| 열 | 내용 |
|---|---|
| `race_id` | |
| `page_key` | `Scm` `Both` `Bc` `3Bc` `3Both` |
| `sub_key` | `3Bc`/`3Both`는 출마번호 문자열, 나머지는 빈 문자열 |
| `table_idx` | 페이지 안 `<table>` 등장 순서, 0부터 |
| `row_idx` | 0부터 |
| `col_idx` | 0부터. **colspan을 펼치지 마라.** 소스에 나타난 셀 순서 그대로 |
| `tag` | `td` 또는 `th` |
| `colspan` `rowspan` | 정수, 없으면 1 |
| `raw_text` | 셀 원문. 앞뒤 공백만 제거. 내부 공백·`&nbsp;`·줄바꿈은 그대로 둔다 |

### `outputs/l1/blocks_<YYYY>.parquet` — 표 **밖**의 텍스트

도착마번이 `<table>`이 아니라 `<fieldset>` 안에 있다. `fieldset` `label` `span` `dl` `dt` `dd`를 문서 순으로 순회해 `(race_id, page_key, sub_key, tag, seq, raw_text)`로 저장해라.

**어느 것이 도착순인지 판정하지 마라.** 전부 담는다. 고르는 건 나중 일이다.

### `outputs/l1/meta.parquet`

경주별 `meta`를 평탄화. `base_page_checks`와 `retry_history`는 JSON 문자열로 그대로 넣어라.

### `outputs/l1/probe.parquet`

`3Bc`/`3Both`의 `_probe` 값을 그대로. 해석하지 마라.

## 실행 순서

1. **표본 100경주 먼저.** race_id 정렬 후 균등 간격으로 뽑아 연도가 고르게 섞이게 해라.
2. 다음을 출력해라 — 존재하는 연도, 총 파일 수, 페이지당 `<table>` 개수 분포, 셀 총수, `raw_text` 고유값 빈도 상위 50개.
3. 그게 말이 되면 전수로 간다.

## 코드

`analysis/l1_parse.py` 하나. lxml 써도 된다.

**`pandas.read_html`은 쓰지 마라.** 그건 셀을 이미 해석해서 colspan을 펼치고 숫자로 바꾼다. 좌표가 망가진다.

**예외를 except로 감싸 넘기지 마라.** 그대로 터뜨려라. 조용한 실패가 이 프로젝트를 두 번 망쳤다.

## 막히면

멈추고 물어라. 추측해서 진행하지 마라. 선택지를 늘어놓지도 마라 — 판단이 있으면 그것만 말하고, 없으면 없다고 해라.
