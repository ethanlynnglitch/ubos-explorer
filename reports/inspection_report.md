# UBOS Source File Inspection Report

**Scope:** structural inspection only of the workbooks in `data/raw/`. No files were modified, renamed, moved or deleted. No ingestion, cleaning, database or dashboard code was written.

**Method:** `openpyxl` (`data_only=True`, i.e. cached formula results) for `.xlsx`; `xlrd 2.0.1` for the legacy `.xls`. `xlrd` was installed into `.venv` because neither `pandas` nor `openpyxl` can read BIFF8 `.xls`. Row/column references below are **Excel-style 1-based**.

Statements are marked **[F]** for facts read directly out of the files and **[A]** for assumptions/inferences.

---

## 1. Inventory of `data/raw/`

| File | Format | Size | Sheets | Content (per its own titles) |
|---|---|---|---|---|
| `03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx` | OOXML (xlsx) | 432 KB | 17 | Quarterly GDP, constant 2016/17 prices, up to 2025/26 Q2 |
| `03_2026QGDP_Current_Prices_Q2_2025_26.xlsx` | OOXML (xlsx) | 280 KB | 11 | Quarterly GDP, current prices, up to 2025/26 Q2 |
| `06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx` | OOXML (xlsx) | 673 KB | 18 | Quarterly GDP, constant 2016/17 prices, up to 2025/26 Q3 |
| `06_2026QGDP_Current_Prices_Q3_2025-26.xlsx` | OOXML (xlsx) | 284 KB | 11 | Quarterly GDP, current prices, up to 2025/26 Q3 |
| `06_2026AGDP_Publication_Tables_2025_26_June_Release.xls` | BIFF8 (legacy xls) | 326 KB | 15 | Annual (fiscal-year) GDP publication tables |

All five are Excel workbooks. **[F]**

Embedded document properties: the `.xls` was created 2004-01-29 and last saved 2026-06-04; the `.xlsx` files were last modified 2026-04-09 (the two `03_…Q2` files) and 2026-06-11 / 2026-06-23 (the two `06_…Q3` files). **[F]**
The `03_`/`06_` filename prefixes therefore appear to be the release month (March vs June). **[A]**

There are two release vintages of the same quarterly product: a March release ending 2025/26 Q2 and a June release ending 2025/26 Q3. **[A, based on F above]**

---

## 2. Quarterly workbooks (the four `.xlsx` files)

### 2.1 Sheet inventory

Constant-price workbooks (Q2 file / Q3 file):
`USE OF DATA`, `Summary`, `Summary IPD`*, `Original_VA`, `Original_Growth`, `Original_IPD`, `Deseason_VA`, `Deseason_Growth`, `Deseason_Growth_Decomp`, `Deseason`*, `Trend_VA`, `Trend_Growth`, `TS IPD`*, `Graphs`/`Graphs (2)`, `Original_Expenditure`, `Deseason_Exp`, `Graphs Original`*.
The Q3 file has one extra chart sheet (`Graphs (2)`). **[F]**

Current-price workbooks:
`Summary`, `Original_VA`, `Original_%share`, `Deseason_VA`, `Deseason_%share`, `Trend_VA`, `Trend_%share`, `Original_Expenditure`, `Deseason_Exp`, `OS VA CP Growth`*, `SA VA CKP growth`*. **[F]**

`*` = sheet is **hidden**. Hidden sheets are: `Summary IPD`, `Deseason`, `TS IPD`, `Graphs Original` (constant files) and `OS VA CP Growth`, `SA VA CKP growth` (current files). **[F]**

### 2.2 Layout of the activity ("VA") sheets — the main data sheets

Example: `Original_VA` in `03_2026QGDP_Constant_Prices_Q2_2025_26.xlsx` (`A1:AM37`). **[F]**

| Row | Content |
|---|---|
| 1 | Title: `Table 3: ORIGINAL UNADJUSTED Value Added by activity at constant 2016/17 prices…` |
| 2 | blank |
| 3 | `Year` in A; fiscal-year labels (`2016/17`, `2017/18`, …) in **merged** 4-cell blocks (`B3:E3`, `F3:I3`, …) |
| 4 | `Period` in A; `Q1 Q2 Q3 Q4` repeating per fiscal year |
| 5 | `GDP AT MARKET PRICES` (aggregate) |
| 6–33 | Activity rows; `AGRICULTURE,FORESTRY&FISHING` (6), `INDUSTRY` (13), `SERVICES` (19) are section aggregates, remaining rows are their components |
| 34 | blank |
| 35 | `ADJUSTMENTS` (section label, no data) |
| 36 | `Taxes on products` |
| 37 | Footnote: `Source: Uganda Bureau of Statistics` |

So: **two header rows (3 and 4), one title row (1), one section-label row (35), one footnote row (37), a single table per sheet.** **[F]**

The 33 labels in A5:A37 are identical across all four quarterly workbooks except two cosmetic differences: `Financial & Insurance` vs `Financial and Insurance`, and the footnote `Source: Uganda Bureau of Statistics` vs plain `Uganda Bureau of Statistics` in the current-price files. **[F]**

**Addendum (found during ingestion, 2026-08-22):** the statement above holds for `Original_VA` only, which is all that was compared for the first draft of this report. The `Deseason_VA` and `Trend_VA` sheets of the two **current-price** workbooks carry a seasonal-adjustment suffix in the row label itself: row 18 reads `Construction SA` in `Deseason_VA` and `Construction Trend` in `Trend_VA`, against plain `Construction ` in `Original_VA`. Current-price `Trend_VA` also switches the section aggregates to title case (`Industry`, `Services` rather than `INDUSTRY`, `SERVICES`). Row 18 was confirmed to be the Construction component in all three sheets: rows 14–18 sum exactly to the `INDUSTRY` aggregate on row 13 in each case. **[F]** No other row labels differ.

Hierarchy is only encoded by ALL-CAPS aggregates and leading spaces in the label text; there is no level column. **[F]**

### 2.3 Column/period coverage — differs by vintage

| Workbook | `Original_VA` columns | Period range |
|---|---|---|
| `03…Constant…Q2` | B:AM (38 quarter columns) | 2016/17 Q1 → 2025/26 Q2 |
| `03…Current…Q2` | B:AM (38) | 2016/17 Q1 → 2025/26 Q2 |
| `06…Current…Q3` | B:AN (39) | 2016/17 Q1 → 2025/26 Q3 |
| `06…Constant…Q3` | **I:CC (73)** plus a stray annual block in B:F | **2007/08 Q3** → 2025/26 Q3 |

**[F]** The June constant-price workbook was rebuilt with the full back series from 2007/08 Q3 and, in the same rows, carries an unrelated block of **annual fiscal-year totals in columns B–F** (`2013/14`…`2017/18`, labelled in row 4 where the other columns hold `Q1..Q4`), with columns G–H empty/zero. **[F]**

Cross-check: for the 38 quarters present in both constant-price vintages, sampled values (GDP, Agriculture, Industry, Services, Taxes) are **bit-identical** — no revisions between the March and June releases in those series. **[F]** This matches note (b) on the `USE OF DATA` sheet. **[F]**

### 2.4 Other sheet types

- **`Summary`** — contains **two stacked tables** on one sheet, each with its own title and its own two-row header:
  `03…Constant…Q2!Summary`: Table 1 (levels) rows 2–29, Table 2 (percentage change) rows 31–57; each block repeats sub-headings `ORIGINAL ESTIMATES`, `SEASONALLY ADJUSTED ESTIMATES`, `TREND CYCLE ESTIMATES` and ends with a `Source:` line. **[F]**
- **`Original_Expenditure` / `Deseason_Exp`** — expenditure-side GDP with a **three-row header**: row 1 calendar year, row 2 fiscal year, row 3 quarter (plus the sheet's own caption in B3/B1). Labels are in column **B**, not A. Rows 4–25 are the levels table; rows 27–49 are a second `QUARTERLY CHANGES` table. Everything below row ~50 is empty even though `max_row` is reported as 166/167. **[F]**
- **`USE OF DATA`** (constant-price files only) — documentation sheet: a 7-row guidance table (rows 2–9) and eight lettered notes (rows 12–19). No statistics. **[F]**
- **`Graphs`, `Graphs (2)`, `Graphs Original`** — effectively empty (chart holders). **[F]**
- **Hidden sheets** `Summary IPD`, `Deseason`, `TS IPD`, `OS VA CP Growth`, `SA VA CKP growth` — dominated by cached `#REF!` errors (e.g. every data cell of `Deseason` and `TS IPD` in the Q2 constant file). **[F]** They look like stale working sheets. **[A]**

---

## 3. Annual workbook (`…AGDP_Publication_Tables…xls`)

### 3.1 Sheets

| Sheet | Rows × Cols | Visible? | Tables it contains |
|---|---|---|---|
| `Contents` | 28 × 4 | hidden | index of Tables 1 – 11.2 |
| `Summary` | 32 × 12 | hidden | Table 1 – summary statistics |
| `GDP CP` | 78 × 13 | hidden | Table 2.1 (levels) + Table 2.2 (% contribution) |
| `GDP KP` | 78 × 13 | hidden | Table 3.1 (levels) + Table 3.2 (% growth) |
| `IPD` | 78 × 13 | hidden | Table 4.1 (deflators) + Table 4.2 (% growth) |
| `U5 GO` | 112 × 13 | **visible** | Tables 5.1/5.2/5.3 "Gross Output" — **all data cells are `#REF!`** |
| `U6 IC` | 112 × 13 | **visible** | Tables 6.1/6.2/6.3 "Intermediate Consumption" — **all data cells are `#REF!`** |
| `Formal` | 75 × 13 | hidden | Tables 5.1 / 5.2 – formal sector |
| `Informal` | 74 × 13 | hidden | Tables 6.1 / 6.2 – informal sector |
| `GDP Exp CP` | 29 × 12 | hidden | Table 7.1 – expenditure, current prices |
| `GDP Exp KP` | 29 × 11 | hidden | Table 7.2 – expenditure, constant prices |
| `Market` | 75 × 13 | hidden | Tables 8.1 / 8.2 |
| `Non Market` | 74 × 13 | hidden | Tables 9.1 / 9.2 |
| `Own_Account Production` | 74 × 13 | hidden | Tables 10.1 / 10.2 |
| `Sector GDP` | 40 × 12 | hidden | Tables 11.1 / 11.2 – institutional sectors |

**[F]** Only the two broken sheets are visible; every sheet holding real numbers is hidden. **[F]**
`U5 GO` / `U6 IC` reuse table numbers 5.x and 6.x that `Contents` assigns to `Formal` / `Informal`, and `Contents` does not list Gross Output or Intermediate Consumption at all — so they are stale leftovers from an older edition. **[A, on F]**
Their year headers also start at 2008/09 while every working sheet starts at 2016/17. **[F]**

### 3.2 Layout of an annual sheet

`GDP CP` (representative of `GDP KP`, `IPD`, `Formal`, `Informal`, `Market`, `Non Market`, `Own_Account Production`): **[F]**

| Excel row | Content |
|---|---|
| 2 | `Table 2.1` |
| 3 | `Gross domestic product by economic activity` |
| 4 | `Current prices (billion shillings)` (units line) |
| 5 | blank |
| 6 | header: col C `ISIC`, cols D–M fiscal years `2016/17` … `2025/26` |
| 7 | blank |
| 8 | `GDP at market prices` (row labels are in column **B**; column A is empty) |
| 9–36 | activity rows, each with an ISIC letter code in column C |
| 37 | blank |
| 38 | `Taxes on products` |
| 39–41 | blank separator |
| 42 | `Table 2.2` — second table starts, same skeleton (title 42, subtitle 43, units 44, header 46, data 48–78) |

So most annual sheets hold **two tables stacked vertically**, separated by blank rows, with the second table containing derived measures (shares / growth / deflator growth). **[F]**
No merged cells anywhere in the `.xls`. **[F]**
Row completeness was checked on `Summary`, `GDP CP`, `Informal`, `Sector GDP`: every data row has all 10 year values, no error cells. **[F]**

Exceptions to the skeleton: **[F]**
- `GDP Exp CP` / `GDP Exp KP` have no ISIC column, no blank spacer rows, and the header sits on row 3; `GDP Exp KP` is shifted one column left (labels in column **A**, years in **B–K**) while `GDP Exp CP` has labels in **B** and years in **C–L**. `GDP Exp KP` also repeats `Table 7.2` on both rows 1 and 2.
- `Sector GDP` puts the year header on row 3 and the units caption (`Current Prices`) *below* it on row 4.
- `Summary` is a mixed-unit table (levels, indices, growth rates, per-capita, population, exchange rate) with a footnote in row 32: `**PPP=2.842$ according to International Program survey (ICP) 2016/17`.

---

## 4. Which sheets contain real statistical observations

**Annual `.xls` — usable:** `Summary`, `GDP CP`, `GDP KP`, `IPD`, `Formal`, `Informal`, `GDP Exp CP`, `GDP Exp KP`, `Market`, `Non Market`, `Own_Account Production`, `Sector GDP`. **Not usable:** `Contents` (index), `U5 GO`, `U6 IC` (all `#REF!`). **[F]**

**Quarterly `.xlsx` — usable:** `Summary`, `Original_VA`, `Original_Growth`, `Original_IPD`, `Original_%share`, `Deseason_VA`, `Deseason_Growth`, `Deseason_Growth_Decomp`, `Deseason_%share`, `Trend_VA`, `Trend_Growth`, `Trend_%share`, `Original_Expenditure`, `Deseason_Exp`. **Not usable:** `USE OF DATA`, the `Graphs*` sheets, and the hidden `#REF!` sheets listed in §2.4. **[F]**

Caveat: in the June constant-price workbook, `Original_Growth`, `Original_IPD`, `Deseason_Growth`, `Deseason_Growth_Decomp` and `Trend_Growth` contain 80–210 cached `#DIV/0!` / `#VALUE!` cells, concentrated in the earliest columns where the back series has no prior period to compare against. **[F / A on the cause]**

---

## 5. Important columns and what they represent

Both families are **wide (period-across-columns)** layouts. **[F]**

Row dimension (all activity sheets): a single label column holding a mixed hierarchy of *GDP aggregate → sector aggregate → activity*, plus an `ADJUSTMENTS`/`Taxes on products` tail. In the annual workbook a second column carries the **ISIC letter code** (`A`, `AA`, `AB`, `B`, `C`, …), which is the closest thing to a stable activity key in the whole dataset. The quarterly workbooks have **no ISIC column**. **[F]**

Column dimension:
- Annual: one column per **fiscal year** `YYYY/YY`, 2016/17 → 2025/26 (10 years). **[F]**
- Quarterly: one column per **fiscal-year quarter**, identified by the fiscal-year label in row 3 (merged over its quarters) plus `Q1..Q4` in row 4. Expenditure sheets add a calendar-year row above. **[F]**
- Uganda's fiscal year runs July–June, so FY `2016/17` Q1 = Jul–Sep 2016. **[A]** — consistent with the calendar-year row of the expenditure sheets, where `2016/17` spans calendar 2016 Q3/Q4 and 2017 Q1/Q2. **[F]**

Measures present, distinguishable by sheet name / title: value added levels (billion shillings), % growth, % share/contribution, implicit price deflators, growth decomposition; each in Original (unadjusted), Seasonally adjusted, and Trend-cycle variants; plus expenditure-side aggregates (FCE, GFCF, inventories, exports, imports, statistical discrepancy, GDP at market prices) and institutional-sector and formal/informal/market/non-market/own-account breakdowns. **[F]**

Units are stated only in prose in the title/units line (e.g. "BILLION SHILLINGS", "Constant 2016/17 Prices", "% contribution to GDP"); there is no unit column. **[F]**

---

## 6. Similarities and differences

**Similarities [F]**
- Same conceptual framework: same activity breakdown, same 2016/17 constant-price base, same "billion shillings" unit, same UBOS source footnote.
- Wide layout, title rows above, header rows, data block, footnote below.
- Both families expose Original / Seasonally adjusted / Trend variants (quarterly) or level / derived-measure pairs (annual).
- The 33 quarterly activity labels are effectively identical across all four quarterly workbooks.

**Differences [F]**
| Aspect | Quarterly `.xlsx` | Annual `.xls` |
|---|---|---|
| Format | OOXML | BIFF8 (needs `xlrd`) |
| Period | fiscal quarter | fiscal year |
| Header rows | 2 (or 3 on expenditure sheets) | 1 (year row), with title/units rows above |
| Merged cells | yes, year labels merged across quarters | none |
| ISIC codes | absent | present |
| Tables per sheet | 1, except `Summary` and expenditure sheets (2) | 2 on most sheets |
| Sheet visibility | data sheets visible, junk hidden | data sheets hidden, junk visible |
| Label style | `AGRICULTURE,FORESTRY&FISHING`, `Trade & Repairs` | `Agriculture, forestry and fishing`, `Wholesale and retail trade…` |

Label wording therefore does **not** match between the annual and quarterly families and will need a crosswalk. **[F/A]**

Within the quarterly family, the June constant-price workbook is the structural outlier (73 quarter columns from 2007/08, stray annual block in B–F, unmerged repeated year labels on expenditure sheets, error cells), while the other three follow the compact 2016/17-onwards layout. **[F]**

---

## 7. Problems that will make automated extraction difficult

1. **Header row/column positions are not constant.** They vary by sheet and by workbook (`Summary` year row on row 3 vs 4; `GDP Exp KP` shifted one column left; expenditure sheets use column B for labels). Hard-coded `skiprows`/`usecols` will silently break. **[F]**
2. **Merged year headers.** In the quarterly files the fiscal year appears only in the top-left cell of a 4-column merge, so it must be forward-filled — but the June constant-price workbook *repeats* the year in every column instead, and the March constant `Summary` has irregular merges (`B3:E3` then `G3:I3` with a separate value in `F3`). Both patterns must be handled. **[F]**
3. **Missing quarter labels.** On `03…Constant…Q2!Original_Expenditure` the first fiscal year's columns C–F have no `Q1..Q4` labels in row 3 (labels start at G); on `06…Constant…Q3!Original_Expenditure` quarter labels are absent for all columns before AP. Periods cannot be derived from row 3 alone. **[F]**
4. **Corrupt period headers in the back series of the June constant-price workbook** (found during ingestion, 2026-08-22). In `Deseason_Growth`, columns H–M are labelled `Q1 Q2 Q3 Q4 Q1 Q2` all under fiscal year `2009/10` — six quarters in one fiscal year — and the next year label, `2010/11`, appears at column N against `Q3`, so that fiscal year has only two quarters. In `Deseason_VA`, columns B–G carry no year or quarter labels at all, giving that sheet 67 identifiable quarter columns where its siblings have 73. Both defects lie entirely within the pre-2016/17 back series and therefore do not touch any observation in the current MVP scope, but they rule out any assumption that the quarterly header block is uniformly four-quarters-per-year. **[F]**
5. **Mixed annual and quarterly data in one row.** `06…Constant…Q3` VA sheets hold fiscal-year totals in B–F alongside quarterly values in I–CC. Reading "all numeric columns" will mix two different frequencies into one series. **[F]**
6. **Multiple tables per sheet** separated only by blank rows, with repeated headers and repeated row labels (e.g. `GDP at market prices` appears in both Table 2.1 and Table 2.2 of `GDP CP`; `SEASONALLY ADJUSTED ESTIMATES` blocks repeat within `Summary`). Table boundaries must be detected, not assumed. **[F]**
7. **Cached error values.** `#REF!` fills the hidden quarterly working sheets and both visible annual sheets; `#DIV/0!`/`#VALUE!` appear in the June growth sheets. With `data_only=True` these arrive as strings and will poison numeric columns; `xlrd` returns them as error cells with code 23. **[F]**
8. **Inflated sheet extents.** `max_row`/`max_column` are far larger than the real data (e.g. `Deseason_Exp` reports 222–256 columns and 166 rows for a ~25×40 table). Bounds must be computed from content. **[F]**
9. **Hierarchy encoded in formatting.** Parent/child relationships exist only as ALL-CAPS text and leading spaces; `ADJUSTMENTS` is a label row with no data. Aggregates and components sit in the same column, so naive summing double-counts. **[F]**
10. **Legacy `.xls`.** Not readable by `openpyxl`/`pandas` alone; requires `xlrd` (now installed in `.venv`). **[F]**
11. **The only visible sheets in the annual workbook are broken**, so a "read the visible sheets" heuristic returns nothing but errors. **[F]**
12. **Label instability across sources** (annual vs quarterly wording, `Financial & Insurance` vs `Financial and Insurance`, trailing spaces such as `Accommodation & Food Service  `, `Public Administration  `). Joins on raw labels will fail without normalisation. **[F]**
13. **Two vintages of the same series** (March Q2 release, June Q3 release) overlap for 38 quarters, so a de-duplication / vintage-precedence rule is required. **[F]**
    Now measured exhaustively across all 10,260 overlapping GDP-by-activity series keys (ingestion run 2026-08-22): the **original (unadjusted) constant-price** series — both levels and growth — are **identical across the two vintages**, matching note (b) of the `USE OF DATA` sheet. Everything else is revised: seasonally adjusted and trend-cycle series disagree on 1,114–1,140 keys each, and current-price original levels on 53 keys (largest absolute change 2.4 UGX bn). This is consistent with note (c), which states that seasonally adjusted data are revised as future data arrive. **[F]**
14. **No machine-readable units, base year, or frequency** — all of it lives in free-text title lines that must be parsed or hand-mapped. **[F]**

---

## 8. Open questions for you

1. Should the back series in the June constant-price workbook (2007/08 Q3 onward) be kept, or should the explorer standardise on 2016/17 onward for comparability with the current-price files?
2. When both vintages cover a quarter, should the later (June) release always win?
3. Are the annual `Formal`/`Informal`/`Market`/`Non Market`/`Own_Account`/`Sector GDP` breakdowns in scope, or is the first target GDP by activity plus GDP by expenditure only?
4. Confirm the fiscal-year convention (July–June) so period keys can be dated correctly.
