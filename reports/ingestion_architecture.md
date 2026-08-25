# UBOS Explorer — Ingestion Architecture (MVP)

**Status:** APPROVED and implemented (2026-08-22), with two modifications requested at approval time:
`growth_basis` is left **null/unknown** rather than inferred, and all three quarterly seasonal-adjustment
variants are retained. See `ingestion_qa.md` for the results of the implemented run.
**Companion document:** [`inspection_report.md`](./inspection_report.md) — every structural fact cited here was verified there.
**Scope of this design:** GDP by economic activity, annual + quarterly, levels and growth where the source provides them, fiscal years 2016/17 onward, latest release wins on overlap.

Out of scope for v1: dashboard, DuckDB loader, web scraper, UBOS website discovery, formal/informal/market/non-market/own-account and other specialised breakdowns.

---

## 1. MVP scope — the blocks that get ingested

| Release | Workbook | Sheets / row ranges in scope | Measures produced |
|---|---|---|---|
| 2026-06 AGDP | `06_2026AGDP_Publication_Tables_2025_26_June_Release.xls` | `GDP CP` rows 8–38 (Table 2.1); `GDP KP` rows 8–38 (Table 3.1); `GDP KP` rows 48–78 (Table 3.2) | annual level (current), annual level (constant), annual growth |
| 2026-06 QGDP | `06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx` | `Original_VA`, `Original_Growth`, `Deseason_VA`, `Deseason_Growth`, `Trend_VA`, `Trend_Growth` | quarterly level + growth, constant prices |
| 2026-06 QGDP | `06_2026QGDP_Current_Prices_Q3_2025-26.xlsx` | `Original_VA`, `Deseason_VA`, `Trend_VA` | quarterly level, current prices |
| 2026-03 QGDP | `03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx` | same six sheets as above | superseded vintage |
| 2026-03 QGDP | `03_2026QGDP_Current_Prices_Q2_2025_26.xlsx` | same three sheets as above | superseded vintage |

**Deliberately excluded in v1:** all `Summary` sheets; all `Original_Expenditure` / `Deseason_Exp` sheets; `Original_IPD`, `Summary IPD`, `TS IPD`; `Deseason_Growth_Decomp`; `Original_%share`, `Deseason_%share`, `Trend_%share`; annual Tables 2.2 / 4.1 / 4.2; `Formal`, `Informal`, `Market`, `Non Market`, `Own_Account Production`, `Sector GDP`; `U5 GO`, `U6 IC`; all `Graphs*` sheets; all hidden working sheets.

This exclusion list is doing real architectural work. It removes four of the twelve hazards from the inspection report outright:

- the `Summary` sheets were the **only** in-family sheets with two stacked tables and irregular merge patterns;
- the expenditure sheets were the **only** ones with three-row headers, labels in column B, and missing `Q1..Q4` labels.

What remains is uniform: **nine quarterly sheets per release vintage sharing one identical layout, and three annual blocks sharing another.** The MVP therefore needs exactly **two layout parsers** — no generic table-detection engine.

**Block count (corrected during implementation).** The scope table above enumerates **21** source blocks: 3 annual + (6 constant + 3 current) for the June vintage + (6 constant + 3 current) for the March vintage. Earlier prose in this document said "12", which counted only the June release and the annual workbook; 21 is correct and is what `sources.yml` implements.

---

## 2. Normalized data structure

One tidy fact table, one lineage table, one reject table. Written as Parquet to `data/processed/`. DuckDB reads Parquet directly via `read_parquet()`, so v1 needs no loader code and no database file.

### 2.1 `gdp_observations.parquet` — one row per source cell

| Column | Type | Notes |
|---|---|---|
| `obs_id` | str | sha1 of natural key + `release_id` |
| `frequency` | str | `A` / `Q` |
| `fiscal_year` | str | e.g. `2016/17` |
| `fy_start_year` | int16 | `2016` — for correct chronological sorting |
| `quarter` | int8 (nullable) | 1–4; null for annual |
| `period_id` | str | `2016/17` (annual) or `2016/17Q1` (quarterly) |
| `period_start` | date | derived |
| `period_end` | date | derived |
| `activity_id` | str | canonical id from the crosswalk |
| `activity_label` | str | canonical display label |
| `activity_level` | str | `total` / `sector` / `activity` / `adjustment` |
| `parent_activity_id` | str (nullable) | null for `total` |
| `isic_code` | str (nullable) | annual source only |
| `price_basis` | str | `current` / `constant_2016_17` |
| `adjustment` | str | `original` / `seasonally_adjusted` / `trend_cycle` |
| `measure` | str | `level` / `growth_pct` |
| `growth_basis` | str (nullable) | `yoy` / `qoq`; null for levels |
| `unit` | str | `UGX_bn` / `pct` |
| `value` | float64 | |
| `release_id` | str | `2026-06_QGDP`, `2026-03_QGDP`, `2026-06_AGDP` |
| `release_date` | date | |
| `is_current` | bool | vintage-winner flag |
| `source_file` | str | filename as it sits in `data/raw/` |
| `source_sheet` | str | worksheet name |
| `source_table` | str | e.g. `Table 3`, `Table 3.1` |
| `source_cell` | str | e.g. `AL5` |

**Natural key:** (`frequency`, `period_id`, `activity_id`, `price_basis`, `adjustment`, `measure`) plus `release_id`. Uniqueness is asserted at write time.

Expected volume: roughly 20,000 rows. Correctness matters here; performance does not.

### 2.2 `source_blocks.parquet` — extraction manifest

One row per extracted block: `source_id`, `source_file`, **`file_sha256`**, `source_sheet`, `source_table`, the table title string exactly as read from the file, header row numbers used, data row/column ranges used, engine (`openpyxl` / `xlrd`), `release_id`, `extracted_at`, `n_observations`, `n_rejects`.

### 2.3 `rejects.parquet` — everything that did not become an observation

Same coordinate columns as the fact table, plus `raw_value` (as text) and `reject_reason` ∈ {`error_cell`, `non_numeric`, `blank`, `unmapped_label`, `out_of_scope_period`, `not_a_period_column`}. Nothing is dropped silently.

---

## 3. Annual observations

Represented in the same fact table, distinguished by `frequency = 'A'` and `quarter IS NULL`.

- `period_id` uses the bare fiscal year (`2016/17`), which cannot collide with the quarterly form (`2016/17Q1`), so an accidental UNION cannot double-count.
- `period_start` / `period_end` span Jul–Jun, letting the dashboard place annual and quarterly series on one time axis.
- `isic_code` is populated (annual source only) and is the most stable activity key available anywhere in the dataset.
- Annual data is unadjusted, so `adjustment = 'original'` for all annual rows.

The **July–June fiscal calendar is an assumption**, corroborated by the calendar-year header row of the expenditure sheets (FY `2016/17` spans calendar 2016 Q3/Q4 and 2017 Q1/Q2). It is implemented in a single function, `fy_quarter_to_dates()`, so a correction touches one place.

---

## 4. Quarterly observations

`frequency = 'Q'`, `quarter ∈ {1,2,3,4}`, `period_id = '<fy>Q<n>'`.

The period is reconstructed from **two header rows**: the fiscal year on row 3 (merged across its four quarters) and `Q1..Q4` on row 4. Reconstruction rules:

1. Read row 3 across the sheet and **forward-fill** to expand merged blocks.
2. Accept a column as a data column only if row 4 ∈ {`Q1`,`Q2`,`Q3`,`Q4`} **and** the filled row-3 value matches `^\d{4}/\d{2}$`.
3. Everything else is not a period column and is recorded as such in `rejects`.

The same rule handles the June workbook's *unmerged, repeated* year labels with no special case, because forward-fill of an already-populated row is a no-op.

---

## 5. Current-price vs constant-price

An explicit `price_basis` dimension, **declared per source block in config** rather than parsed out of free-text titles. The value `constant_2016_17` encodes the base year, so a future UBOS rebasing cannot silently mix two bases in one series.

Annual current prices come from `GDP CP`; annual constant prices from `GDP KP`.

**Consequence of the source data, not a pipeline gap:** quarterly current-price workbooks contain no growth table (only `%share`, out of scope), and the annual current-price sheet's second block is `% contribution`, not growth. Therefore `measure = 'growth_pct'` will exist **only** for `price_basis = 'constant_2016_17'`. The QA report states this explicitly so it is not later mistaken for a bug.

**Resolved at approval: `growth_basis` is NOT inferred.** The workbooks label these tables only "PERCENTAGE CHANGE" and nowhere state whether the change is year-on-year or quarter-on-quarter. Growth observations are therefore preserved with `growth_basis = null` until the basis can be verified against authoritative UBOS documentation. No guess is encoded anywhere in the pipeline.

---

## 6. Release vintages

Every vintage is extracted and **retained**. Deduplication is a flag, never a delete.

1. `release_date` is taken from the workbook's document properties (2026-04-09 for the March pair, 2026-06-23 and 2026-06-11 for the June pair), overridable per block in config.
2. Rows are ranked by `release_date` within the natural key; the newest gets `is_current = true`.
3. Where two vintages disagree beyond a relative tolerance of 1e-6, the conflict is written to `reports/ingestion_qa.md`.

Step 3 earns its place: constant-price `Original_VA` was verified bit-identical across the two vintages, but the current-price and growth sheets were not checked, so silent divergence is possible.

The dashboard filters `WHERE is_current`; the full audit trail survives underneath.

---

## 7. Aggregates vs component activities

A hand-written crosswalk, `src/ubos_explorer/config/activities.csv`, is the single source of truth for the activity dimension. Both workbook families use the **same 30 activity rows in the same order** (verified: 1 GDP total + 3 sector aggregates + 25 component activities + 1 adjustment row). Earlier prose in this document said 31; 30 is correct. The file is short and one-off:

```csv
activity_id,label,level,parent_id,isic,alias_annual,alias_quarterly
gdp_market_prices,GDP at market prices,total,,,GDP at market prices,GDP AT MARKET PRICES
agriculture,"Agriculture, Forestry & Fishing",sector,gdp_market_prices,A,"Agriculture, forestry and fishing","AGRICULTURE,FORESTRY&FISHING"
cash_crops,Cash crops,activity,agriculture,AA,Cash crops,Cash crops
...
taxes_on_products,Taxes on products,adjustment,gdp_market_prices,,Taxes on products,Taxes on products
```

- Matching is on a **normalized alias**: casefold, unify `&` / `and`, then strip every non-alphanumeric character. This absorbs the known variants (`Financial & Insurance` vs `Financial and Insurance`, `AGRICULTURE,FORESTRY&FISHING` vs `Agriculture, forestry and fishing`, `Accommodation & Food Service  `, `Public Administration  `).
- The hard-failure rule earned its keep immediately: on the first run it caught `Construction SA` and `Construction Trend`, labels used on row 18 of the current-price `Deseason_VA` / `Trend_VA` sheets that the inspection report had missed (it compared `Original_VA` only). Row 18 was verified to be the Construction component — rows 14–18 sum exactly to the `INDUSTRY` aggregate — and the two labels were then added as explicit verified aliases. Had unmatched labels been skipped silently, Construction would simply have vanished from six of the nine current-price series.
- **An unmatched label is a hard failure**, not a silent skip — a silent skip is how an entire activity disappears from the dashboard unnoticed.
- Double-counting is prevented *structurally*: `activity_level` + `parent_activity_id` force every query to state its grain (`WHERE activity_level = 'sector'`). There is no "flat list of rows" for a careless `SUM()` to add up.
- The `ADJUSTMENTS` label row carries no data and is dropped during extraction. `Taxes on products` is modelled as `level = 'adjustment'` with parent `gdp_market_prices` — it is not a component of any sector.

**Additivity QA (per period, per price basis, per adjustment):**

- `sum(sector levels) + taxes_on_products ≈ gdp_market_prices`, tolerance 0.5%
- `sum(component levels) ≈ parent sector level`, tolerance 0.5%

Violations are written to the QA report. This catches column-misalignment — the single most likely failure mode given these headers — far more reliably than unit tests would.

---

## 8. Source lineage

Two levels of traceability:

**Cell level**, on every fact row: `source_file` + `source_sheet` + `source_table` + `source_cell`. Any figure shown in the dashboard traces to, e.g., `06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx › Original_VA › AL5`, which can be opened in Excel and eyeballed.

**Block level**, `source_blocks.parquet`: filename, **sha256 of the raw file**, sheet, the title string as read from the file, the exact header and data ranges used, engine, and extraction timestamp. The hash proves which byte-identical input produced a given output and detects later tampering with `data/raw/`.

`data/raw/` is opened read-only. Nothing in the pipeline writes, renames, moves or deletes anything in it.

---

## 9. How each identified hazard is handled

| Hazard (from the inspection report) | Handling |
|---|---|
| Header row/column positions vary by sheet and workbook | Explicit per-block config in `sources.yml`, not heuristics. With 21 blocks across 5 files, enumeration is cheaper and safer than inference. |
| Merged fiscal-year headers | Forward-fill row 3, validate against `^\d{4}/\d{2}$`. The same code path handles the June file's unmerged repeated labels. |
| Stray **annual** block in columns B–F of the June constant-price workbook | Column filter requires row 4 ∈ {Q1..Q4} *and* a valid fiscal year on filled row 3. The annual block fails (row 4 holds `2013/14`) and drops out automatically. `first_data_col: I` is pinned in config as a second guard. |
| 2007/08–2015/16 back series | `min_fiscal_year: 2016/17` filter applied *after* parsing, so the number of dropped observations is logged rather than invisible. |
| Multiple tables per sheet | Avoided entirely for quarterly (Summary excluded). For the three annual blocks the row ranges are pinned in config from the verified layout. No table detector needed. |
| Cached `#REF!`, `#DIV/0!`, `#VALUE!` | Type-gate every cell: openpyxl must return `int`/`float` (excluding `bool`); xlrd must return `XL_CELL_NUMBER`. Anything else, plus NaN/inf, goes to `rejects.parquet` with a reason and cell address. Errors can never reach the fact table. |
| Inflated `max_row` / `max_column` | Never consulted. Ranges come from config; extraction stops at the declared last row. |
| Legacy `.xls` | A thin `io_excel` adapter with two backends exposing one `read_cell(row, col) -> Value | Error` interface. Layout parsers stay engine-agnostic. Requires `xlrd==2.0.1` (already installed in `.venv`). |
| Broken sheets visible, good sheets hidden | Sheet visibility is ignored completely; only the config allowlist is read. `U5 GO` and `U6 IC` are never opened. |
| Label instability across sources | Alias normalization in the crosswalk; unmatched label = hard error. |
| Overlapping release vintages | `is_current` flag plus a conflict report (§6). |
| No machine-readable units, base year or frequency | Declared per block in config; the sheet's own title string is stored in `source_blocks` so the declaration can be audited against what the file actually says. |

---

## 10. Code layout and effort

```
src/ubos_explorer/
  config/sources.yml        # 21 block descriptors — the only file that changes per release
  config/activities.csv     # 30-row activity crosswalk
  io_excel.py               # openpyxl/xlrd adapter, error-cell detection
  layouts.py                # quarterly_va() and annual_isic() -> (records, rejects)
  normalize.py              # period parsing, crosswalk join, scope filters
  vintage.py                # release ranking, is_current, conflict detection
  qa.py                     # additivity checks, reject summary -> reports/ingestion_qa.md
  pipeline.py               # CLI entry point: python -m ubos_explorer.pipeline

data/raw/                   # untouched, read-only
data/processed/             # gdp_observations.parquet, source_blocks.parquet, rejects.parquet
reports/                    # inspection_report.md, ingestion_architecture.md, ingestion_qa.md
```

Example block descriptor:

```yaml
- source_id: qgdp_2026_06_const_original_va
  file: 06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx
  engine: openpyxl
  sheet: Original_VA
  release: { id: 2026-06_QGDP, date: 2026-06-23 }
  frequency: Q
  price_basis: constant_2016_17
  adjustment: original
  measure: level
  unit: UGX_bn
  layout: quarterly_va       # year_row: 3, quarter_row: 4, label_col: A, data_rows: 5-36
  first_data_col: I          # guard against the stray annual block in B-F
  drop_labels: [ADJUSTMENTS]
```

Estimated ~450 lines of Python; **actual: 1,299 lines** (868 Python + 391 config), the overshoot being almost entirely the QA module and the 21-block config. Two parsers, no table-detection engine, no database, no scraper. Adding a future UBOS release is a config edit. Adding the formal/informal or institutional-sector breakdowns in a later phase reuses `annual_isic` unchanged.

---

## 11. Questions raised before implementation (both resolved at approval)

1. **`growth_basis`** — RESOLVED at approval: left null/unknown. Still requires authoritative UBOS documentation before it can be populated.
2. **Seasonal-adjustment breadth** — RESOLVED at approval: all three variants (`original`, `seasonally_adjusted`, `trend_cycle`) are retained.
