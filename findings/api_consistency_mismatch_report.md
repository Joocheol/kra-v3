# KRA OpenAPI vs Dropbox archive consistency findings

This note records mismatches found while comparing KRA OpenAPI race IDs with the Dropbox raw archive under:

```text
/kra-analysis/data/raw_collected_v3_15w
```

The comparison target is the race identifier convention:

```text
YYYY-MM-DD_meet_rcNo
```

where `meet` is the numeric meet code used in the archive file names.

## Current status

- GitHub Actions uses the repository secret `DATA_GO_KR_SERVICE_KEY` to build API race-id manifests.
- API manifests are uploaded as artifacts named `kra-api-race-ids-YYYY`.
- In the 2026-08-18 run, manifests succeeded for 2017, 2019, 2022, 2023, 2024, and 2025.
- In the same run, 2016 and 2018 failed at the API query step and should be retried with larger timeout/retry limits.
- Dropbox archive listing is available through the ChatGPT Dropbox connector, but full set comparison must distinguish `api_only` from `archive_only`; monthly total counts alone are not sufficient because the two sides can offset within a month.

## 2025 directly confirmed `api_only` records

The following 2025 races were directly checked against Dropbox metadata and confirmed to exist in the API manifest but not in the Dropbox raw archive.

```csv
race_id,date,weekday,meet,rc_no,note
2025-05-24_2_02,2025-05-24,Saturday,2,2,individual confirmed missing
2025-08-02_3_01,2025-08-02,Saturday,3,1,Busan-Gyeongnam block confirmed missing
2025-08-02_3_02,2025-08-02,Saturday,3,2,Busan-Gyeongnam block confirmed missing
2025-08-02_3_03,2025-08-02,Saturday,3,3,Busan-Gyeongnam block confirmed missing
2025-08-02_3_04,2025-08-02,Saturday,3,4,Busan-Gyeongnam block confirmed missing
2025-08-02_3_05,2025-08-02,Saturday,3,5,Busan-Gyeongnam block confirmed missing
2025-08-09_3_01,2025-08-09,Saturday,3,1,Busan-Gyeongnam block confirmed missing
2025-08-09_3_02,2025-08-09,Saturday,3,2,Busan-Gyeongnam block confirmed missing
2025-08-09_3_03,2025-08-09,Saturday,3,3,Busan-Gyeongnam block confirmed missing
2025-08-09_3_04,2025-08-09,Saturday,3,4,Busan-Gyeongnam block confirmed missing
2025-08-09_3_05,2025-08-09,Saturday,3,5,Busan-Gyeongnam block confirmed missing
2025-08-09_3_06,2025-08-09,Saturday,3,6,Busan-Gyeongnam block confirmed missing
2025-08-09_3_07,2025-08-09,Saturday,3,7,Busan-Gyeongnam block confirmed missing
2025-08-09_3_08,2025-08-09,Saturday,3,8,Busan-Gyeongnam block confirmed missing
2025-08-09_3_09,2025-08-09,Saturday,3,9,Busan-Gyeongnam block confirmed missing
2025-10-02_2_01,2025-10-02,Thursday,2,1,Jeju block confirmed missing
2025-10-02_2_02,2025-10-02,Thursday,2,2,Jeju block confirmed missing
2025-10-02_2_03,2025-10-02,Thursday,2,3,Jeju block confirmed missing
2025-10-02_2_04,2025-10-02,Thursday,2,4,Jeju block confirmed missing
2025-10-02_2_05,2025-10-02,Thursday,2,5,Jeju block confirmed missing
2025-10-02_2_06,2025-10-02,Thursday,2,6,Jeju block confirmed missing
2025-10-02_2_07,2025-10-02,Thursday,2,7,Jeju block confirmed missing
2025-10-02_2_08,2025-10-02,Thursday,2,8,Jeju block confirmed missing
2025-10-02_3_01,2025-10-02,Thursday,3,1,Busan-Gyeongnam block confirmed missing
2025-10-02_3_02,2025-10-02,Thursday,3,2,Busan-Gyeongnam block confirmed missing
2025-10-02_3_03,2025-10-02,Thursday,3,3,Busan-Gyeongnam block confirmed missing
2025-10-02_3_04,2025-10-02,Thursday,3,4,Busan-Gyeongnam block confirmed missing
2025-10-02_3_05,2025-10-02,Thursday,3,5,Busan-Gyeongnam block confirmed missing
2025-10-02_3_06,2025-10-02,Thursday,3,6,Busan-Gyeongnam block confirmed missing
2025-10-02_3_07,2025-10-02,Thursday,3,7,Busan-Gyeongnam block confirmed missing
2025-10-02_3_08,2025-10-02,Thursday,3,8,Busan-Gyeongnam block confirmed missing
2025-10-03_1_01,2025-10-03,Friday,1,1,Seoul block confirmed missing
2025-10-03_1_02,2025-10-03,Friday,1,2,Seoul block confirmed missing
2025-10-03_1_03,2025-10-03,Friday,1,3,Seoul block confirmed missing
2025-10-03_1_04,2025-10-03,Friday,1,4,Seoul block confirmed missing
2025-10-03_1_05,2025-10-03,Friday,1,5,Seoul block confirmed missing
2025-10-03_1_06,2025-10-03,Friday,1,6,Seoul block confirmed missing
2025-10-03_1_07,2025-10-03,Friday,1,7,Seoul block confirmed missing
2025-10-03_1_08,2025-10-03,Friday,1,8,Seoul block confirmed missing
2025-10-03_1_09,2025-10-03,Friday,1,9,Seoul block confirmed missing
2025-10-03_1_10,2025-10-03,Friday,1,10,Seoul block confirmed missing
2025-10-03_1_11,2025-10-03,Friday,1,11,Seoul block confirmed missing
2025-10-04_3_01,2025-10-04,Saturday,3,1,Busan-Gyeongnam block confirmed missing
2025-10-04_3_02,2025-10-04,Saturday,3,2,Busan-Gyeongnam block confirmed missing
2025-10-04_3_03,2025-10-04,Saturday,3,3,Busan-Gyeongnam block confirmed missing
2025-10-04_3_04,2025-10-04,Saturday,3,4,Busan-Gyeongnam block confirmed missing
2025-10-04_3_05,2025-10-04,Saturday,3,5,Busan-Gyeongnam block confirmed missing
2025-10-04_3_06,2025-10-04,Saturday,3,6,Busan-Gyeongnam block confirmed missing
2025-12-13_2_06,2025-12-13,Saturday,2,6,individual confirmed missing
```

Confirmed count so far: 49 API-only races.

## Observed pattern

The confirmed missing dates are mostly Saturdays, plus a 2025-10-02 to 2025-10-04 holiday/weekend-adjacent block:

- 2025-05-24, Saturday
- 2025-08-02, Saturday
- 2025-08-09, Saturday
- 2025-10-02, Thursday
- 2025-10-03, Friday
- 2025-10-04, Saturday
- 2025-12-13, Saturday

This pattern suggests block-level collection gaps rather than random individual parse failures, but this remains a diagnostic interpretation until the full bidirectional diff is completed.

## Next required checks

1. Complete exact set comparison for all target years: 2016, 2017, 2018, 2019, 2022, 2023, 2024, and 2025.
2. For each year, write both:
   - `api_only_YYYY.csv`: races in KRA OpenAPI but absent from Dropbox raw archive.
   - `archive_only_YYYY.csv`: races in Dropbox raw archive but absent from KRA OpenAPI.
3. Do not rely on monthly totals alone, because `api_only` and `archive_only` can offset within the same month.
4. Retry 2016 and 2018 API manifest generation with larger timeout/retry settings.
