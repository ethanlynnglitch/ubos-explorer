-- UBOS Explorer - analytical views.
--
-- These are the surfaces the dashboard should query. They exist so that the
-- semantics that are easy to get wrong (double-counting aggregates, summing an
-- incomplete fiscal year, mixing release vintages) are visible in every result
-- set rather than left to the caller to remember.

-- Fully denormalised observation view: every vintage, every series.
CREATE OR REPLACE VIEW v_observation AS
SELECT
    f.obs_id,
    p.frequency,
    p.fiscal_year,
    p.fy_start_year,
    p.quarter,
    p.period_id,
    p.period_start,
    p.period_end,
    p.has_four_quarters,
    f.activity_id,
    a.label            AS activity_label,
    a.activity_level,
    a.parent_activity_id,
    a.isic_code,
    a.sort_order,
    f.price_basis,
    f.adjustment,
    f.measure,
    f.growth_basis,
    f.unit,
    f.value,
    f.release_id,
    r.release_label,
    b.release_date,
    f.is_current,
    b.source_file,
    b.source_sheet,
    b.source_table,
    f.source_cell
FROM fact_gdp_observation f
JOIN dim_period       p ON p.period_id  = f.period_id
JOIN dim_activity     a ON a.activity_id = f.activity_id
JOIN dim_source_block b ON b.source_id  = f.source_id
JOIN dim_release      r ON r.release_id = f.release_id;

-- The default dashboard surface: latest UBOS release only (query 8).
CREATE OR REPLACE VIEW v_observation_current AS
SELECT * FROM v_observation WHERE is_current;

-- Annual series (queries 1, 3, 4).
CREATE OR REPLACE VIEW v_gdp_annual AS
SELECT * FROM v_observation_current WHERE frequency = 'A';

-- Quarterly series (queries 5, 6).
CREATE OR REPLACE VIEW v_gdp_quarterly AS
SELECT * FROM v_observation_current WHERE frequency = 'Q';

-- Sector comparison: Agriculture / Industry / Services (query 7).
-- activity_level is pre-filtered so these rows are mutually exclusive and safe
-- to sum.
CREATE OR REPLACE VIEW v_gdp_sectors AS
SELECT * FROM v_observation_current WHERE activity_level = 'sector';

-- Activity hierarchy with parent labels (query 2).
CREATE OR REPLACE VIEW v_activity_tree AS
SELECT
    a.activity_id,
    a.label,
    a.activity_level,
    a.parent_activity_id,
    p.label AS parent_label,
    a.isic_code,
    a.sort_order
FROM dim_activity a
LEFT JOIN dim_activity p ON p.activity_id = a.parent_activity_id
ORDER BY a.sort_order;

-- Full lineage for a single observation (query 9): workbook, worksheet,
-- published table, exact cell, file hash and how it was parsed.
CREATE OR REPLACE VIEW v_lineage AS
SELECT
    f.obs_id,
    f.value,
    f.unit,
    p.period_id,
    a.label AS activity_label,
    f.price_basis,
    f.adjustment,
    f.measure,
    b.source_file,
    b.file_sha256,
    b.source_sheet,
    b.source_table,
    b.table_title,
    f.source_cell,
    b.engine,
    b.layout,
    b.header_rows,
    b.data_rows,
    b.release_id,
    b.release_date,
    b.extracted_at
FROM fact_gdp_observation f
JOIN dim_period       p ON p.period_id   = f.period_id
JOIN dim_activity     a ON a.activity_id = f.activity_id
JOIN dim_source_block b ON b.source_id   = f.source_id;

-- Revision analysis: series carried by more than one release vintage.
CREATE OR REPLACE VIEW v_release_comparison AS
SELECT
    period_id,
    activity_id,
    activity_label,
    price_basis,
    adjustment,
    measure,
    unit,
    COUNT(*)                                        AS n_releases,
    MIN(value)                                      AS min_value,
    MAX(value)                                      AS max_value,
    MAX(value) - MIN(value)                         AS abs_diff,
    MAX(value) FILTER (WHERE is_current)            AS current_value,
    STRING_AGG(DISTINCT release_id, ', ')           AS releases
FROM v_observation
GROUP BY ALL
HAVING COUNT(DISTINCT release_id) > 1;
