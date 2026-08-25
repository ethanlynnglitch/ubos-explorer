"""Build the DuckDB analytical layer from the validated Parquet outputs.

The Parquet files in ``data/processed/`` remain the source of truth. The DuckDB
database is a derived, disposable artifact: it is rebuilt from scratch on every
run, so the same Parquet inputs always produce the same database content.

Usage::

    python -m ubos_explorer.warehouse            # rebuild data/ubos.duckdb
    python -m ubos_explorer.warehouse --check    # verify without rebuilding
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import duckdb

from .io_excel import file_sha256

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]
SQL_DIR = PACKAGE_DIR / "sql"

PARQUET_FILES = {
    "observations": "gdp_observations.parquet",
    "source_blocks": "source_blocks.parquet",
    "rejects": "rejects.parquet",
}

# Tables whose content defines the build fingerprint (meta_build is excluded
# because it carries the wall-clock build time).
CONTENT_TABLES = [
    "dim_release",
    "dim_source_block",
    "dim_activity",
    "dim_period",
    "fact_gdp_observation",
    "stg_reject",
    "dim_series_label",
]

TABLE_ORDER = CONTENT_TABLES + ["meta_build"]

# Presentation strings only - no statistical values. Codes that do not appear
# in the data are discarded at load time.
SERIES_LABELS = [
    ("price_basis", "current", "Current prices", "Nominal, not adjusted for inflation"),
    ("price_basis", "constant_2016_17", "Constant 2016/17 prices", "Volume measure, base year 2016/17"),
    ("adjustment", "original", "Original (unadjusted)", "As published, no seasonal adjustment"),
    ("adjustment", "seasonally_adjusted", "Seasonally adjusted", "Revised as later data arrive"),
    ("adjustment", "trend_cycle", "Trend-cycle", "Smoothed; revised as later data arrive"),
    ("measure", "level", "Value added (UGX bn)", None),
    (
        "measure",
        "growth_pct",
        "Percentage change",
        "UBOS labels these tables only 'PERCENTAGE CHANGE'; the basis "
        "(year-on-year vs quarter-on-quarter) is not stated in the source",
    ),
]


class IntegrityError(Exception):
    """A post-load integrity check failed."""


def _sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def _p(processed_dir: Path, key: str) -> str:
    return str(processed_dir / PARQUET_FILES[key])


def load(con: duckdb.DuckDBPyConnection, processed_dir: Path) -> None:
    """Populate every table from Parquet, parents first (foreign keys)."""
    obs = _p(processed_dir, "observations")
    blocks = _p(processed_dir, "source_blocks")
    rejects = _p(processed_dir, "rejects")

    # -- releases: derived from the block manifest -------------------------
    con.execute(
        """
        INSERT INTO dim_release
        SELECT
            b.release_id,
            CASE WHEN b.release_id LIKE '%AGDP' THEN 'AGDP' ELSE 'QGDP' END,
            CASE WHEN b.release_id LIKE '%AGDP'
                 THEN 'Annual GDP publication tables, ' || SPLIT_PART(b.release_id, '_', 1)
                 ELSE 'Quarterly GDP release, ' || SPLIT_PART(b.release_id, '_', 1)
            END,
            MIN(b.release_date),
            MAX(b.release_date),
            COUNT(*),
            SUM(b.n_observations)
        FROM read_parquet(?) b
        GROUP BY b.release_id
        ORDER BY b.release_id
        """,
        [blocks],
    )

    # -- source blocks -----------------------------------------------------
    con.execute(
        """
        INSERT INTO dim_source_block
        SELECT
            source_id, release_id, source_file, file_sha256, source_sheet,
            source_table, table_title, engine, layout, header_rows, data_rows,
            data_cols, period_columns_found, frequency, price_basis, adjustment,
            measure, unit, release_date, extracted_at, n_observations, n_rejects
        FROM read_parquet(?)
        ORDER BY source_id
        """,
        [blocks],
    )

    # -- activities --------------------------------------------------------
    # sort_order is derived from the worksheet row each activity occupies in
    # the source tables, which preserves UBOS publication order. It is never
    # hand-assigned.
    con.execute(
        """
        CREATE TEMP TABLE _activity AS
        WITH first_row AS (
            SELECT
                activity_id,
                ANY_VALUE(activity_label)     AS label,
                ANY_VALUE(activity_level)     AS activity_level,
                ANY_VALUE(parent_activity_id) AS parent_activity_id,
                ANY_VALUE(isic_code)          AS isic_code,
                MIN(CAST(REGEXP_EXTRACT(source_cell, '(\\d+)$', 1) AS INTEGER)) AS sheet_row
            FROM read_parquet(?)
            GROUP BY activity_id
        )
        SELECT
            activity_id, label, activity_level, parent_activity_id, isic_code,
            CAST(ROW_NUMBER() OVER (ORDER BY sheet_row, activity_id) AS INTEGER) AS sort_order
        FROM first_row
        """,
        [obs],
    )
    # The self-referencing foreign key is checked per statement, so parents have
    # to be committed before their children: total -> sectors -> everything else.
    for levels in (("total",), ("sector",), ("activity", "adjustment")):
        con.execute(
            """
            INSERT INTO dim_activity
            SELECT activity_id, label, activity_level, parent_activity_id,
                   isic_code, sort_order
            FROM _activity
            WHERE activity_level IN ?
            ORDER BY sort_order
            """,
            [list(levels)],
        )
    con.execute("DROP TABLE _activity")

    # -- periods -----------------------------------------------------------
    con.execute(
        """
        INSERT INTO dim_period
        WITH periods AS (
            SELECT DISTINCT
                period_id, frequency, fiscal_year, fy_start_year, quarter,
                period_start, period_end
            FROM read_parquet(?)
        ),
        coverage AS (
            SELECT fiscal_year, COUNT(DISTINCT quarter) AS n_quarters
            FROM read_parquet(?)
            WHERE frequency = 'Q'
            GROUP BY fiscal_year
        )
        SELECT
            p.period_id, p.frequency, p.fiscal_year, p.fy_start_year, p.quarter,
            p.period_start, p.period_end,
            COALESCE(c.n_quarters, 0) = 4
        FROM periods p
        LEFT JOIN coverage c ON c.fiscal_year = p.fiscal_year
        ORDER BY p.fy_start_year, p.frequency, p.quarter
        """,
        [obs, obs],
    )

    # -- facts -------------------------------------------------------------
    con.execute(
        """
        INSERT INTO fact_gdp_observation
        SELECT
            obs_id, period_id, activity_id, source_id, release_id,
            price_basis, adjustment, measure, unit, growth_basis,
            value, is_current, source_cell
        FROM read_parquet(?)
        ORDER BY obs_id
        """,
        [obs],
    )

    # -- rejects -----------------------------------------------------------
    con.execute(
        """
        INSERT INTO stg_reject
        SELECT
            source_id, source_file, source_sheet, source_table, source_cell,
            "row", "col", row_label, fiscal_year, quarter, raw_value,
            reject_reason, in_scope, release_id
        FROM read_parquet(?)
        ORDER BY source_id, "row", "col"
        """,
        [rejects],
    )

    # -- presentation labels ----------------------------------------------
    con.execute(
        "CREATE TEMP TABLE _labels(attribute VARCHAR, code VARCHAR, "
        "display_label VARCHAR, note VARCHAR)"
    )
    con.executemany("INSERT INTO _labels VALUES (?, ?, ?, ?)", SERIES_LABELS)
    con.execute(
        """
        INSERT INTO dim_series_label
        SELECT l.*
        FROM _labels l
        WHERE EXISTS (
            SELECT 1 FROM fact_gdp_observation f
            WHERE (l.attribute = 'price_basis' AND f.price_basis = l.code)
               OR (l.attribute = 'adjustment'  AND f.adjustment  = l.code)
               OR (l.attribute = 'measure'     AND f.measure     = l.code)
        )
        ORDER BY l.attribute, l.code
        """
    )
    con.execute("DROP TABLE _labels")


def content_hash(con: duckdb.DuckDBPyConnection) -> str:
    """Deterministic fingerprint of all data tables, excluding build metadata."""
    parts = []
    for table in CONTENT_TABLES:
        digest = con.execute(
            f"SELECT COALESCE(md5(string_agg(CAST(t AS VARCHAR), '|' ORDER BY "
            f"CAST(t AS VARCHAR))), 'empty') FROM {table} t"
        ).fetchone()[0]
        parts.append(f"{table}:{digest}")
    return duckdb.sql(f"SELECT md5('{'|'.join(parts)}')").fetchone()[0]


def write_meta(con: duckdb.DuckDBPyConnection, processed_dir: Path) -> None:
    fingerprint = content_hash(con)
    now = dt.datetime.now()
    version = duckdb.__version__
    for name in PARQUET_FILES.values():
        path = processed_dir / name
        rows = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?)", [str(path)]
        ).fetchone()[0]
        con.execute(
            "INSERT INTO meta_build VALUES (?, ?, ?, ?, ?, ?)",
            [now, version, name, file_sha256(path), rows, fingerprint],
        )


# --------------------------------------------------------------- integrity --

CHECKS: list[tuple[str, str, str]] = [
    (
        "fact row count matches Parquet",
        "SELECT (SELECT COUNT(*) FROM fact_gdp_observation) "
        "- (SELECT row_count FROM meta_build WHERE parquet_file = 'gdp_observations.parquet')",
        "eq0",
    ),
    (
        "reject row count matches Parquet",
        "SELECT (SELECT COUNT(*) FROM stg_reject) "
        "- (SELECT row_count FROM meta_build WHERE parquet_file = 'rejects.parquet')",
        "eq0",
    ),
    (
        "block row count matches Parquet",
        "SELECT (SELECT COUNT(*) FROM dim_source_block) "
        "- (SELECT row_count FROM meta_build WHERE parquet_file = 'source_blocks.parquet')",
        "eq0",
    ),
    (
        "no orphan facts (period/activity/source/release)",
        """SELECT COUNT(*) FROM fact_gdp_observation f
           WHERE NOT EXISTS (SELECT 1 FROM dim_period       d WHERE d.period_id   = f.period_id)
              OR NOT EXISTS (SELECT 1 FROM dim_activity     d WHERE d.activity_id = f.activity_id)
              OR NOT EXISTS (SELECT 1 FROM dim_source_block d WHERE d.source_id   = f.source_id)
              OR NOT EXISTS (SELECT 1 FROM dim_release      d WHERE d.release_id  = f.release_id)""",
        "eq0",
    ),
    (
        "natural key is unique",
        """SELECT COUNT(*) FROM (
             SELECT 1 FROM fact_gdp_observation
             GROUP BY release_id, price_basis, adjustment, measure, activity_id, period_id
             HAVING COUNT(*) > 1)""",
        "eq0",
    ),
    (
        "is_current count matches Parquet",
        "SELECT (SELECT COUNT(*) FROM fact_gdp_observation WHERE is_current) - "
        "(SELECT COUNT(*) FROM read_parquet(?) WHERE is_current)",
        "eq0_param",
    ),
    (
        "every series has exactly one current row",
        """SELECT COUNT(*) FROM (
             SELECT 1 FROM fact_gdp_observation
             GROUP BY price_basis, adjustment, measure, activity_id, period_id
             HAVING COUNT(*) FILTER (WHERE is_current) <> 1)""",
        "eq0",
    ),
    (
        "growth_basis remains unknown",
        "SELECT COUNT(*) FROM fact_gdp_observation "
        "WHERE measure = 'growth_pct' AND growth_basis IS NOT NULL",
        "eq0",
    ),
    (
        "component activities all have a parent",
        "SELECT COUNT(*) FROM dim_activity "
        "WHERE activity_level <> 'total' AND parent_activity_id IS NULL",
        "eq0",
    ),
    (
        "additivity: sectors + taxes = GDP (0.5%)",
        """WITH lv AS (
             SELECT release_id, price_basis, adjustment, period_id, activity_level, value
             FROM fact_gdp_observation f JOIN dim_activity a USING (activity_id)
             WHERE measure = 'level'
           ),
           t AS (SELECT release_id, price_basis, adjustment, period_id, value AS total
                 FROM lv WHERE activity_level = 'total'),
           p AS (SELECT release_id, price_basis, adjustment, period_id, SUM(value) AS parts
                 FROM lv WHERE activity_level IN ('sector', 'adjustment')
                 GROUP BY ALL)
           SELECT COUNT(*) FROM t JOIN p USING (release_id, price_basis, adjustment, period_id)
           WHERE abs(parts - total) / nullif(abs(total), 0) > 0.005""",
        "eq0",
    ),
    (
        "additivity: components = their sector (0.5%)",
        """WITH lv AS (
             SELECT release_id, price_basis, adjustment, period_id, activity_id,
                    parent_activity_id, activity_level, value
             FROM fact_gdp_observation f JOIN dim_activity a USING (activity_id)
             WHERE measure = 'level'
           ),
           s AS (SELECT release_id, price_basis, adjustment, period_id,
                        activity_id, value AS total
                 FROM lv WHERE activity_level = 'sector'),
           c AS (SELECT release_id, price_basis, adjustment, period_id,
                        parent_activity_id AS activity_id, SUM(value) AS parts
                 FROM lv WHERE activity_level = 'activity' GROUP BY ALL)
           SELECT COUNT(*) FROM s JOIN c USING
                 (release_id, price_basis, adjustment, period_id, activity_id)
           WHERE abs(parts - total) / nullif(abs(total), 0) > 0.005""",
        "eq0",
    ),
    (
        "quarterly sums equal published annual GDP for complete years",
        """WITH q AS (
             SELECT fiscal_year, SUM(value) AS qsum
             FROM v_observation_current
             WHERE frequency = 'Q' AND measure = 'level'
               AND price_basis = 'constant_2016_17' AND adjustment = 'original'
               AND activity_id = 'gdp_market_prices' AND has_four_quarters
             GROUP BY fiscal_year
           ),
           a AS (
             SELECT fiscal_year, value AS annual
             FROM v_observation_current
             WHERE frequency = 'A' AND measure = 'level'
               AND price_basis = 'constant_2016_17'
               AND activity_id = 'gdp_market_prices'
           )
           SELECT COUNT(*) FROM q JOIN a USING (fiscal_year)
           WHERE abs(qsum - annual) / nullif(abs(annual), 0) > 1e-9""",
        "eq0",
    ),
]


def run_integrity(con: duckdb.DuckDBPyConnection, processed_dir: Path) -> list[tuple[str, bool, int]]:
    results = []
    for name, sql, kind in CHECKS:
        if kind == "eq0_param":
            value = con.execute(sql, [_p(processed_dir, "observations")]).fetchone()[0]
        else:
            value = con.execute(sql).fetchone()[0]
        results.append((name, value == 0, value))
    return results


def verify_sources(con: duckdb.DuckDBPyConnection, processed_dir: Path) -> list[tuple[str, bool]]:
    """Confirm the Parquet inputs still match what the database was built from."""
    rows = con.execute("SELECT parquet_file, file_sha256 FROM meta_build").fetchall()
    return [
        (name, file_sha256(processed_dir / name) == digest) for name, digest in rows
    ]


# -------------------------------------------------------------------- build --

def build(db_path: Path, processed_dir: Path) -> duckdb.DuckDBPyConnection:
    for name in PARQUET_FILES.values():
        if not (processed_dir / name).exists():
            raise FileNotFoundError(
                f"missing {processed_dir / name}; run "
                f"`python -m ubos_explorer.pipeline` first"
            )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # The database is a derived artifact: always rebuild from scratch so that
    # the same Parquet inputs always yield the same content.
    for path in (db_path, db_path.with_suffix(db_path.suffix + ".wal")):
        if path.exists():
            path.unlink()
    con = duckdb.connect(str(db_path))
    con.execute(_sql("schema.sql"))
    load(con, processed_dir)
    con.execute(_sql("views.sql"))
    write_meta(con, processed_dir)
    return con


def table_report(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, int]]:
    rows = []
    for table in TABLE_ORDER:
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        rows.append((table, "table", count))
    views = con.execute(
        "SELECT view_name FROM duckdb_views() WHERE NOT internal ORDER BY view_name"
    ).fetchall()
    for (view,) in views:
        count = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        rows.append((view, "view", count))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the UBOS DuckDB analytical layer.")
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "ubos.duckdb")
    parser.add_argument(
        "--processed-dir", type=Path, default=PROJECT_ROOT / "data" / "processed"
    )
    parser.add_argument(
        "--check", action="store_true", help="verify an existing database without rebuilding"
    )
    args = parser.parse_args(argv)

    if args.check:
        if not args.db.exists():
            print(f"no database at {args.db}; run without --check to build it")
            return 2
        con = duckdb.connect(str(args.db), read_only=True)
        print(f"database: {args.db}")
    else:
        con = build(args.db, args.processed_dir)
        print(f"built   : {args.db}")

    print(f"source  : {args.processed_dir} (read-only)")
    fingerprint = con.execute("SELECT DISTINCT content_hash FROM meta_build").fetchone()[0]
    print(f"content : {fingerprint}")
    print()

    print(f"{'object':<26} {'kind':<6} {'rows':>10}")
    print("-" * 44)
    for name, kind, count in table_report(con):
        print(f"{name:<26} {kind:<6} {count:>10,}")
    print()

    print("source parquet still matching build:")
    ok_sources = True
    for name, ok in verify_sources(con, args.processed_dir):
        print(f"  [{'OK' if ok else 'CHANGED'}] {name}")
        ok_sources &= ok
    print()

    print("integrity checks:")
    failures = 0
    for name, ok, value in run_integrity(con, args.processed_dir):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"  (got {value})"))
        failures += 0 if ok else 1

    size = args.db.stat().st_size
    print()
    print(f"database size: {size:,} bytes ({size / 1024 / 1024:.2f} MiB)")
    con.close()

    if not ok_sources:
        print(
            "\nSTALE: a Parquet input has changed since this database was built. "
            "Rebuild with `python -m ubos_explorer.warehouse`.",
            flush=True,
        )
    if failures:
        print(f"\n{failures} integrity check(s) failed", flush=True)
    if failures or not ok_sources:
        return 1
    print("\nall integrity checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
