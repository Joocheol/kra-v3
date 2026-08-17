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
- API manifests are uploaded as artifacts named `kra-api-race-ids-YYYY-meet-M` after splitting the smoke test by year and meet.
- API request settings on the PR branch currently use:
  - API request timeout: 60 seconds
  - API retries: 3
  - workflow timeout: 8 minutes per matrix job
  - matrix split: 8 years x 3 meet codes
  - matrix throttling: `max-parallel: 2` to reduce public API timeout risk.
- In run `32077482540`, 2025 succeeded for all three meet codes, so the 2025 API manifest is complete.
- The same run produced a mixture of successes and failures for earlier years. Checked failure logs show the same transient cause:

```text
RuntimeError: API request failed after 4 attempts: <urlopen error timed out>
```

Therefore these failed jobs should be interpreted as public API timeout failures, not as data mismatches.

## Successful API manifest artifacts observed in run 32077482540

The following API manifest artifacts were created successfully:

```text
2016 meet 1
2016 meet 3
2017 meet 1
2017 meet 2
2018 meet 2
2018 meet 3
2019 meet 2
2019 meet 3
2022 meet 1
2023 meet 2
2024 meet 2
2025 meet 1
2025 meet 2
2025 meet 3
```

## Failed API manifest jobs observed in run 32077482540

The following jobs failed due to API timeouts and should be retried under throttled or serial execution:

```text
2016 meet 2
2017 meet 3
2018 meet 1
2019 meet 1
2022 meet 2
2022 meet 3
2023 meet 1
2023 meet 3
2024 meet 1
2024 meet 3
```

## 2025 directly confirmed `api_only` records

The 2025 API manifest is complete: meet 1, meet 2, and meet 3 artifacts jointly contain 2,481 API race IDs. The following records were directly checked against Dropbox metadata and confirmed to exist in the API manifest but not in the Dropbox raw archive. They are also recorded in machine-readable form at:

```text
findings/api_only_2025_confirmed.csv
```

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

Confirmed 2025 API-only count so far: 49 races.

## Observed 2025 pattern

The confirmed missing dates are mostly Saturdays, plus a 2025-10-02 to 2025-10-04 holiday/weekend-adjacent block:

- 2025-05-24, Saturday
- 2025-08-02, Saturday
- 2025-08-09, Saturday
- 2025-10-02, Thursday
- 2025-10-03, Friday
- 2025-10-04, Saturday
- 2025-12-13, Saturday

This pattern suggests block-level collection gaps rather than random individual parse failures, but this remains a diagnostic interpretation until the full bidirectional diff is completed.

## Important caution

Do not infer exact `api_only` or `archive_only` counts from monthly totals alone. In 2025, the Dropbox monthly file count can look close to the API monthly count even when the month contains confirmed API-only records, because API-only and archive-only records may offset within the same month.

## Next required checks

1. Complete exact set comparison for all target years: 2016, 2017, 2018, 2019, 2022, 2023, 2024, and 2025.
2. For each year, write both:
   - `api_only_YYYY.csv`: races in KRA OpenAPI but absent from Dropbox raw archive.
   - `archive_only_YYYY.csv`: races in Dropbox raw archive but absent from KRA OpenAPI.
3. Do not rely on monthly totals alone, because `api_only` and `archive_only` can offset within the same month.
4. Retry failed API manifest jobs with throttled matrix execution or manually rerun failed jobs after reducing public API concurrency.
