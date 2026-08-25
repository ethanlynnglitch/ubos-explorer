# UBOS Explorer - Ingestion QA Report

Generated: 2026-08-22T13:01:43

## Summary

- Source blocks processed: **21**
- Observations written: **21,690**
- Rejected cells: **5,940**
- Current (non-superseded) observations: **11,430**
- Checks failed: **0**, warnings: **2**

## Checks

| Check | Status | Detail |
|---|---|---|
| `natural_key_uniqueness` | PASS | 21,690 rows, no duplicate keys |
| `unmapped_activity_labels` | PASS | every row label matched the crosswalk |
| `period_validity` | PASS | 49 distinct periods, all well formed |
| `period_header_anomalies` | WARN | 4 header anomaly/anomalies detected during parsing (0 affecting in-scope fiscal years) |
| `rejected_cells` | PASS | 5,940 cells rejected; 0 of them are error/non-numeric cells inside the in-scope period range |
| `missing_observations` | PASS | all 723 (block, period) combinations carry the full activity set |
| `additivity` | PASS | all 1928 additivity checks within 0.5% |
| `release_conflicts` | WARN | 10,260 series keys appear in more than one release; 10,260 rows flagged is_current=False; 6,833 series revised between vintages (levels judged on relative diff, percentages on absolute percentage points, tolerance 1e-06) |

### period_header_anomalies (WARN)

| source_id | source_sheet | message |
|---|---|---|
| qgdp_2026_06_const_deseason_growth | Deseason_Growth | duplicate period column 2009/10Q1 at columns 8 and 12 (out of scope) |
| qgdp_2026_06_const_deseason_growth | Deseason_Growth | duplicate period column 2009/10Q2 at columns 9 and 13 (out of scope) |
| qgdp_2026_06_const_deseason_growth | Deseason_Growth | fiscal year 2009/10 has quarters [1, 1, 2, 2, 3, 4] instead of [1, 2, 3, 4] (out of scope) |
| qgdp_2026_06_const_deseason_growth | Deseason_Growth | fiscal year 2010/11 has quarters [3, 4] instead of [1, 2, 3, 4] (out of scope) |

### rejected_cells (PASS)

| reject_reason | in_scope | cells |
|---|---|---|
| out_of_scope_period | False | 5080 |
| error_cell | False | 438 |
| blank | False | 422 |

### release_conflicts (WARN)

| price_basis | adjustment | measure | series_keys | max_abs_diff |
|---|---|---|---|---|
| constant_2016_17 | seasonally_adjusted | growth_pct | 1140 | 10.2317 |
| constant_2016_17 | trend_cycle | growth_pct | 1140 | 26.8009 |
| current | seasonally_adjusted | level | 1138 | 310.302 |
| current | trend_cycle | level | 1133 | 513.925 |
| constant_2016_17 | seasonally_adjusted | level | 1115 | 147.062 |
| constant_2016_17 | trend_cycle | level | 1114 | 255.908 |
| current | original | level | 53 | 2.39099 |

## Observations by release, frequency and measure

| release_id | frequency | price_basis | adjustment | measure | observations |
|---|---|---|---|---|---|
| 2026-03_QGDP | Q | constant_2016_17 | original | growth_pct | 1140 |
| 2026-03_QGDP | Q | constant_2016_17 | original | level | 1140 |
| 2026-03_QGDP | Q | constant_2016_17 | seasonally_adjusted | growth_pct | 1140 |
| 2026-03_QGDP | Q | constant_2016_17 | seasonally_adjusted | level | 1140 |
| 2026-03_QGDP | Q | constant_2016_17 | trend_cycle | growth_pct | 1140 |
| 2026-03_QGDP | Q | constant_2016_17 | trend_cycle | level | 1140 |
| 2026-03_QGDP | Q | current | original | level | 1140 |
| 2026-03_QGDP | Q | current | seasonally_adjusted | level | 1140 |
| 2026-03_QGDP | Q | current | trend_cycle | level | 1140 |
| 2026-06_AGDP | A | constant_2016_17 | original | growth_pct | 300 |
| 2026-06_AGDP | A | constant_2016_17 | original | level | 300 |
| 2026-06_AGDP | A | current | original | level | 300 |
| 2026-06_QGDP | Q | constant_2016_17 | original | growth_pct | 1170 |
| 2026-06_QGDP | Q | constant_2016_17 | original | level | 1170 |
| 2026-06_QGDP | Q | constant_2016_17 | seasonally_adjusted | growth_pct | 1170 |
| 2026-06_QGDP | Q | constant_2016_17 | seasonally_adjusted | level | 1170 |
| 2026-06_QGDP | Q | constant_2016_17 | trend_cycle | growth_pct | 1170 |
| 2026-06_QGDP | Q | constant_2016_17 | trend_cycle | level | 1170 |
| 2026-06_QGDP | Q | current | original | level | 1170 |
| 2026-06_QGDP | Q | current | seasonally_adjusted | level | 1170 |
| 2026-06_QGDP | Q | current | trend_cycle | level | 1170 |

## Rejected cells by reason

| reject_reason | in_scope | cells |
|---|---|---|
| blank | False | 422 |
| error_cell | False | 438 |
| out_of_scope_period | False | 5080 |

## Source blocks

| source_id | source_file | source_sheet | source_table | engine | release_id | n_observations | n_rejects |
|---|---|---|---|---|---|---|---|
| agdp_2026_06_gdp_cp_level | 06_2026AGDP_Publication_Tables_2025_26_June_Release.xls | GDP CP | Table 2.1 | xlrd | 2026-06_AGDP | 300 | 0 |
| agdp_2026_06_gdp_kp_level | 06_2026AGDP_Publication_Tables_2025_26_June_Release.xls | GDP KP | Table 3.1 | xlrd | 2026-06_AGDP | 300 | 0 |
| agdp_2026_06_gdp_kp_growth | 06_2026AGDP_Publication_Tables_2025_26_June_Release.xls | GDP KP | Table 3.2 | xlrd | 2026-06_AGDP | 300 | 0 |
| qgdp_2026_06_const_original_va | 06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx | Original_VA | Table 3 | openpyxl | 2026-06_QGDP | 1170 | 1020 |
| qgdp_2026_06_const_original_growth | 06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx | Original_Growth | Table 4 | openpyxl | 2026-06_QGDP | 1170 | 1020 |
| qgdp_2026_06_const_deseason_va | 06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx | Deseason_VA | Table 6 | openpyxl | 2026-06_QGDP | 1170 | 840 |
| qgdp_2026_06_const_deseason_growth | 06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx | Deseason_Growth | Table 7 | openpyxl | 2026-06_QGDP | 1170 | 1020 |
| qgdp_2026_06_const_trend_va | 06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx | Trend_VA | Table 9 | openpyxl | 2026-06_QGDP | 1170 | 1020 |
| qgdp_2026_06_const_trend_growth | 06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx | Trend_Growth | Table 10 | openpyxl | 2026-06_QGDP | 1170 | 1020 |
| qgdp_2026_06_curr_original_va | 06_2026QGDP_Current_Prices_Q3_2025-26.xlsx | Original_VA | Table 13 | openpyxl | 2026-06_QGDP | 1170 | 0 |
| qgdp_2026_06_curr_deseason_va | 06_2026QGDP_Current_Prices_Q3_2025-26.xlsx | Deseason_VA | Table 15 | openpyxl | 2026-06_QGDP | 1170 | 0 |
| qgdp_2026_06_curr_trend_va | 06_2026QGDP_Current_Prices_Q3_2025-26.xlsx | Trend_VA | Table 17 | openpyxl | 2026-06_QGDP | 1170 | 0 |
| qgdp_2026_03_const_original_va | 03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx | Original_VA | Table 3 | openpyxl | 2026-03_QGDP | 1140 | 0 |
| qgdp_2026_03_const_original_growth | 03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx | Original_Growth | Table 4 | openpyxl | 2026-03_QGDP | 1140 | 0 |
| qgdp_2026_03_const_deseason_va | 03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx | Deseason_VA | Table 6 | openpyxl | 2026-03_QGDP | 1140 | 0 |
| qgdp_2026_03_const_deseason_growth | 03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx | Deseason_Growth | Table 7 | openpyxl | 2026-03_QGDP | 1140 | 0 |
| qgdp_2026_03_const_trend_va | 03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx | Trend_VA | Table 9 | openpyxl | 2026-03_QGDP | 1140 | 0 |
| qgdp_2026_03_const_trend_growth | 03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx | Trend_Growth | Table 10 | openpyxl | 2026-03_QGDP | 1140 | 0 |
| qgdp_2026_03_curr_original_va | 03_2026QGDP_Current_Prices_Q2_2025_26.xlsx | Original_VA | Table 13 | openpyxl | 2026-03_QGDP | 1140 | 0 |
| qgdp_2026_03_curr_deseason_va | 03_2026QGDP_Current_Prices_Q2_2025_26.xlsx | Deseason_VA | Table 15 | openpyxl | 2026-03_QGDP | 1140 | 0 |
| qgdp_2026_03_curr_trend_va | 03_2026QGDP_Current_Prices_Q2_2025_26.xlsx | Trend_VA | Table 17 | openpyxl | 2026-03_QGDP | 1140 | 0 |

## Known limitations

- `growth_basis` is deliberately **null** for every growth observation. The workbooks label these tables only "PERCENTAGE CHANGE" and do not state whether the change is year-on-year or quarter-on-quarter. This will remain unknown until it can be verified against authoritative UBOS documentation.
- The July-June fiscal-year convention used to derive `period_start`/`period_end` is an assumption (see `normalize.FY_START_MONTH`).
