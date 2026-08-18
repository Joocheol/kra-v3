# KRA OpenAPI vs Dropbox archive consistency findings

## Final status

- Source smoke run: `32078736924` (24/24 year×meet artifacts succeeded).
- API race IDs: **20,777** unique records; duplicate API race IDs: **0**.
- Dropbox-archive-derived canonical race index: **19,301** unique records.
- Exact intersection: **19,301** races.
- API only: **1,476** races.
- Archive only: **0** races.
- Previously hand-confirmed 2025 API-only subset reproduced: **49/49**.

The archive index is `데이터/races.jsonl.gz`, generated from the Dropbox root recorded in `데이터/manifest.json` as `/kra-analysis/data/raw_collected_v3_15w`. The Dropbox connector was also checked and exposes the same eight yearly source folders.

## Exact counts by year

| year | API | archive | matched | API only | archive only |
|---:|---:|---:|---:|---:|---:|
| 2016 | 2,778 | 1,539 | 1,539 | 1,239 | 0 |
| 2017 | 2,734 | 2,715 | 2,715 | 19 | 0 |
| 2018 | 2,726 | 2,703 | 2,703 | 23 | 0 |
| 2019 | 2,712 | 2,673 | 2,673 | 39 | 0 |
| 2022 | 2,375 | 2,356 | 2,356 | 19 | 0 |
| 2023 | 2,501 | 2,435 | 2,435 | 66 | 0 |
| 2024 | 2,470 | 2,454 | 2,454 | 16 | 0 |
| 2025 | 2,481 | 2,426 | 2,426 | 55 | 0 |
| **Total** | **20,777** | **19,301** | **19,301** | **1,476** | **0** |

## API manifest counts by year × meet

| year | meet 1 | meet 2 | meet 3 | total |
|---:|---:|---:|---:|---:|
| 2016 | 1,113 | 857 | 808 | 2,778 |
| 2017 | 1,094 | 835 | 805 | 2,734 |
| 2018 | 1,100 | 820 | 806 | 2,726 |
| 2019 | 1,101 | 808 | 803 | 2,712 |
| 2022 | 985 | 696 | 694 | 2,375 |
| 2023 | 1,062 | 715 | 724 | 2,501 |
| 2024 | 1,051 | 695 | 724 | 2,470 |
| 2025 | 1,042 | 722 | 717 | 2,481 |

## Machine-readable exact differences

For each target year, the exact set differences are committed under `findings/api_consistency_diff/` as:

- `api_only_YYYY.csv`
- `archive_only_YYYY.csv`
- `summary.csv`

These are exact race-ID set differences, not differences inferred from monthly totals.

## Interpretation

The smoke-test timeouts observed in earlier attempts were transport failures. They disappeared after retries; all 24 manifests were ultimately produced. Any nonzero final differences reported above therefore represent coverage differences between the KRA OpenAPI race index and the preserved Dropbox archive-derived race index, not failed API jobs.

The comparison is about race presence/absence only. It does not by itself establish that every field inside a matched race file is identical to the current API response.
