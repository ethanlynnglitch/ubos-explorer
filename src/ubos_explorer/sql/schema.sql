-- UBOS Explorer - analytical schema (DuckDB).
--
-- Structure only. Every row is loaded from the validated Parquet outputs in
-- data/processed/ by ubos_explorer.warehouse; no observation is ever written
-- literally into this file.
--
-- Tables are created parent-first so that foreign keys can be declared inline.

-- ---------------------------------------------------------------- releases --
CREATE TABLE dim_release (
    release_id          VARCHAR PRIMARY KEY,
    release_family      VARCHAR NOT NULL,          -- QGDP | AGDP
    release_label       VARCHAR NOT NULL,
    -- release_date is NOT functionally dependent on release_id: the June QGDP
    -- release spans two workbooks saved on different dates. The authoritative
    -- per-workbook date lives on dim_source_block; these two columns are for
    -- display only and must not be used for vintage logic.
    first_workbook_date DATE    NOT NULL,
    last_workbook_date  DATE    NOT NULL,
    n_blocks            INTEGER NOT NULL,
    n_observations      INTEGER NOT NULL,
    CHECK (release_family IN ('QGDP', 'AGDP')),
    CHECK (first_workbook_date <= last_workbook_date)
);

-- ------------------------------------------------------------ source blocks --
CREATE TABLE dim_source_block (
    source_id            VARCHAR PRIMARY KEY,
    release_id           VARCHAR NOT NULL REFERENCES dim_release (release_id),
    source_file          VARCHAR NOT NULL,
    file_sha256          VARCHAR NOT NULL,
    source_sheet         VARCHAR NOT NULL,
    source_table         VARCHAR NOT NULL,
    table_title          VARCHAR,
    engine               VARCHAR NOT NULL,
    layout               VARCHAR NOT NULL,
    header_rows          VARCHAR,
    data_rows            VARCHAR,
    data_cols            VARCHAR,
    period_columns_found INTEGER,
    frequency            VARCHAR NOT NULL,
    price_basis          VARCHAR NOT NULL,
    adjustment           VARCHAR NOT NULL,
    measure              VARCHAR NOT NULL,
    unit                 VARCHAR NOT NULL,
    release_date         DATE    NOT NULL,          -- authoritative vintage date
    extracted_at         TIMESTAMP,
    n_observations       INTEGER NOT NULL,
    n_rejects            INTEGER NOT NULL,
    CHECK (engine IN ('openpyxl', 'xlrd')),
    CHECK (frequency IN ('A', 'Q'))
);

-- -------------------------------------------------------------- activities --
CREATE TABLE dim_activity (
    activity_id        VARCHAR PRIMARY KEY,
    label              VARCHAR NOT NULL,
    activity_level     VARCHAR NOT NULL,           -- total|sector|activity|adjustment
    parent_activity_id VARCHAR REFERENCES dim_activity (activity_id),
    isic_code          VARCHAR,
    sort_order         INTEGER NOT NULL,           -- UBOS publication order
    CHECK (activity_level IN ('total', 'sector', 'activity', 'adjustment')),
    -- Only the GDP total may be parentless.
    CHECK ((activity_level = 'total') = (parent_activity_id IS NULL))
);

-- ----------------------------------------------------------------- periods --
CREATE TABLE dim_period (
    period_id         VARCHAR PRIMARY KEY,
    frequency         VARCHAR NOT NULL,
    fiscal_year       VARCHAR NOT NULL,
    fy_start_year     SMALLINT NOT NULL,
    quarter           TINYINT,
    period_start      DATE NOT NULL,
    period_end        DATE NOT NULL,
    -- TRUE when this fiscal year has all four quarters published. 2025/26 has
    -- only three, so summing its quarters understates the year by ~25%.
    has_four_quarters BOOLEAN NOT NULL,
    CHECK (frequency IN ('A', 'Q')),
    CHECK ((frequency = 'A' AND quarter IS NULL)
           OR (frequency = 'Q' AND quarter BETWEEN 1 AND 4)),
    CHECK (period_start < period_end)
);

-- ------------------------------------------------------------------- facts --
CREATE TABLE fact_gdp_observation (
    obs_id       VARCHAR PRIMARY KEY,
    period_id    VARCHAR NOT NULL REFERENCES dim_period (period_id),
    activity_id  VARCHAR NOT NULL REFERENCES dim_activity (activity_id),
    source_id    VARCHAR NOT NULL REFERENCES dim_source_block (source_id),
    release_id   VARCHAR NOT NULL REFERENCES dim_release (release_id),
    price_basis  VARCHAR NOT NULL,
    adjustment   VARCHAR NOT NULL,
    measure      VARCHAR NOT NULL,
    unit         VARCHAR NOT NULL,
    -- Deliberately NULL: UBOS labels the growth tables only "PERCENTAGE
    -- CHANGE" and never states whether the basis is year-on-year or
    -- quarter-on-quarter. Populate only from authoritative documentation.
    growth_basis VARCHAR,
    value        DOUBLE NOT NULL,
    is_current   BOOLEAN NOT NULL,                 -- authoritative; do not recompute
    source_cell  VARCHAR NOT NULL,
    CHECK (price_basis IN ('current', 'constant_2016_17')),
    CHECK (adjustment IN ('original', 'seasonally_adjusted', 'trend_cycle')),
    CHECK (measure IN ('level', 'growth_pct')),
    CHECK (unit IN ('UGX_bn', 'pct')),
    CHECK (isfinite(value)),
    -- The Hour 1 natural-key uniqueness check, promoted into the schema.
    UNIQUE (release_id, price_basis, adjustment, measure, activity_id, period_id)
);

-- ----------------------------------------------------------------- rejects --
-- Audit trail, not part of the star: reject rows have cell coordinates but no
-- obs_id, because by definition they never became observations.
CREATE TABLE stg_reject (
    source_id     VARCHAR NOT NULL REFERENCES dim_source_block (source_id),
    source_file   VARCHAR NOT NULL,
    source_sheet  VARCHAR NOT NULL,
    source_table  VARCHAR NOT NULL,
    source_cell   VARCHAR NOT NULL,
    "row"         INTEGER NOT NULL,
    "col"         INTEGER NOT NULL,
    row_label     VARCHAR,
    fiscal_year   VARCHAR,
    quarter       TINYINT,
    raw_value     VARCHAR,
    reject_reason VARCHAR NOT NULL,
    in_scope      BOOLEAN NOT NULL,
    release_id    VARCHAR NOT NULL REFERENCES dim_release (release_id)
);

-- ------------------------------------------------------- presentation labels --
CREATE TABLE dim_series_label (
    attribute     VARCHAR NOT NULL,
    code          VARCHAR NOT NULL,
    display_label VARCHAR NOT NULL,
    note          VARCHAR,
    PRIMARY KEY (attribute, code)
);

-- --------------------------------------------------------------- build meta --
CREATE TABLE meta_build (
    built_at      TIMESTAMP NOT NULL,
    duckdb_version VARCHAR NOT NULL,
    parquet_file  VARCHAR NOT NULL,
    file_sha256   VARCHAR NOT NULL,
    row_count     BIGINT NOT NULL,
    content_hash  VARCHAR
);
