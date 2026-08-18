# KRA OpenAPI179 payout audit — final verification

## Status

The historical payout audit is complete for the project target years `2016–2019, 2022–2025` and meet codes `1, 2, 3`.

- Latest payout workflow run: `31999932861` (`KRA OpenAPI payout audit`, run #7)
- Latest payout workflow conclusion: **success**
- Successful audit job: `95298208336`
- Result artifact: `kra-openapi179-audit`, artifact id `9278047371`
- Target year×meet combinations checked: **24/24**
- Missing target checkpoints: **0**
- Raw checkpoint rows across the 24 target combinations: **143,577**

Earlier workflow runs failed while the collector was being hardened for test discovery, yearly pagination, parenthesized horse numbers, resumable checkpoints, and API placeholder handling. Two successive later payout runs succeeded; no current failed payout job remains to rerun.

## Project coverage check

The exact race-id comparison uses the committed archive-derived race index `데이터/races.jsonl.gz` against the successful API179 artifact.

| metric | count |
|---|---:|
| archive/project races in target years | 19,301 |
| API179 races in target years | 20,682 |
| matched archive races | 19,301 |
| archive-only races | **0** |
| API179-only races | 1,381 |

Thus **every one of the 19,301 project races is represented in API179**. The API179-only count is a coverage difference, not a payout mismatch. Most of the 2016 excess precedes the archive collection window; later excesses include known archive collection gaps.

The detailed 24-combination counts are stored in `findings/openapi179_payout_audit_by_meet.csv`.

## Payout audit results

For the target project years, the successful artifact contains:

- realized payouts: **212,308**
- realized payouts above `9999.9`: **144**
- payout mismatch candidates after comparing archived finishing order with API179 realized payout rows: **1**

Project-period realized payout maxima are:

| pool | maximum odds | race | winning combination |
|---|---:|---|---|
| 단승식 | 234.9 | `2019-11-15_3_01` | 4 |
| 연승식 | 48.1 | `2018-02-25_3_01` | 4 |
| 복승식 | 4,281.4 | `2019-03-08_3_07` | 12-8 |
| 쌍승식 | 6,487.5 | `2019-03-08_3_07` | 12-8 |
| 복연승식 | 773.5 | `2017-06-11_3_05` | 15-4 |
| 삼복승식 | 17,274.2 | `2017-06-11_3_05` | 15-3-4 |
| 삼쌍승식 | **391,736.8** | `2017-06-11_3_05` | 15-3-4 |

## The single mismatch candidate

The only payout-level candidate is:

- race: `2016-07-01_2_08` (Jeju, race 8)
- pool: `연승식`
- turnover: `197,800` won
- archived finishing order begins `8-4-3`
- expected place-winning combination not present in API179 realized payouts: horse `3`
- API179 realized payout text: `④-1.3  ⑧-1.5`
- the archived `Scm` page has exactly one `9999.9` placeholder in this race

This is therefore best classified as a **payout-representation mismatch / no-ticket-or-placeholder case**, not a missing race or failed API collection. API179 reports realized paid combinations `4` and `8`, while the archived result page implies horse `3` is also a finishing-position winner and contains the `9999.9` placeholder. The machine-readable record is in `findings/openapi179_payout_mismatches.csv`.

This cross-check does not by itself distinguish every institutional reason for the omitted API179 payout (for example, no winning ticket versus a legacy display convention), so the record is retained explicitly rather than silently recoded.

## Conclusion

All 24 target year×meet combinations are successfully collected and verified. API179 covers all 19,301 project races, and the payout comparison leaves exactly **one explicitly documented representation mismatch candidate**. There is no remaining failed payout workflow job requiring retry.
