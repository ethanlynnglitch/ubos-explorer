"""Read-only query layer over the DuckDB analytical database.

Deliberately free of any Streamlit import so it stays testable and reusable.
Caching lives in the app layer.

Every query reads ``v_observation_current``, i.e. the latest UBOS release only.
Superseded vintages remain in the database but are not surfaced here.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "data" / "ubos.duckdb"

GDP_TOTAL = "gdp_market_prices"


class WarehouseMissing(Exception):
    """The DuckDB database has not been built yet."""


def connect(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    path = Path(db_path or DEFAULT_DB)
    if not path.exists():
        raise WarehouseMissing(
            f"no database at {path}. Build it with:\n"
            f"  PYTHONPATH=src python -m ubos_explorer.warehouse"
        )
    return duckdb.connect(str(path), read_only=True)


def _q(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pd.DataFrame:
    # A fresh cursor per query keeps concurrent Streamlit reruns safe.
    return con.cursor().execute(sql, params or []).df()


# ------------------------------------------------------------------ metadata --

def available_series(con) -> pd.DataFrame:
    """Which (frequency, price_basis, adjustment, measure) combinations exist.

    Needed because the source is not a full cube: growth is published only for
    constant prices, and the annual tables carry only unadjusted data.
    """
    return _q(
        con,
        """
        SELECT frequency, price_basis, adjustment, measure, unit,
               COUNT(DISTINCT period_id) AS n_periods
        FROM v_observation_current
        GROUP BY ALL
        ORDER BY frequency, price_basis, adjustment, measure
        """,
    )


def labels(con) -> dict[tuple[str, str], tuple[str, str | None]]:
    frame = _q(con, "SELECT attribute, code, display_label, note FROM dim_series_label")
    return {
        (row.attribute, row.code): (row.display_label, row.note)
        for row in frame.itertuples()
    }


def activities(con) -> pd.DataFrame:
    return _q(
        con,
        """
        SELECT activity_id, label, activity_level, parent_activity_id,
               parent_label, isic_code, sort_order
        FROM v_activity_tree
        ORDER BY sort_order
        """,
    )


def periods(con, frequency: str) -> pd.DataFrame:
    return _q(
        con,
        """
        SELECT DISTINCT period_id, fiscal_year, quarter, period_start,
               has_four_quarters
        FROM v_observation_current
        WHERE frequency = ?
        ORDER BY period_start
        """,
        [frequency],
    )


def build_info(con) -> pd.DataFrame:
    return _q(
        con,
        """
        SELECT parquet_file, row_count, file_sha256, built_at, duckdb_version,
               content_hash
        FROM meta_build ORDER BY parquet_file
        """,
    )


def source_blocks(con) -> pd.DataFrame:
    return _q(
        con,
        """
        SELECT source_id, source_file, source_sheet, source_table, table_title,
               engine, frequency, price_basis, adjustment, measure,
               release_id, release_date, n_observations, n_rejects, file_sha256
        FROM dim_source_block
        ORDER BY release_date DESC, source_file, source_sheet
        """,
    )


# ---------------------------------------------------------------- headline ---

def headline(con) -> pd.DataFrame:
    """Latest published annual and quarterly totals, for the metric row."""
    return _q(
        con,
        """
        WITH ranked AS (
            SELECT frequency, price_basis, measure, adjustment, fiscal_year,
                   period_id, value, unit, has_four_quarters,
                   ROW_NUMBER() OVER (
                       PARTITION BY frequency, price_basis, measure, adjustment
                       ORDER BY period_start DESC
                   ) AS rn
            FROM v_observation_current
            WHERE activity_id = ? AND adjustment = 'original'
        )
        SELECT frequency, price_basis, measure, fiscal_year, period_id, value,
               unit, has_four_quarters
        FROM ranked WHERE rn = 1
        """,
        [GDP_TOTAL],
    )


# ------------------------------------------------------------------ series ---

def series(
    con,
    frequency: str,
    price_basis: str,
    measure: str,
    adjustments: list[str],
    activity_ids: list[str],
) -> pd.DataFrame:
    """Time series for the given activities. One row per period per activity."""
    if not adjustments or not activity_ids:
        return pd.DataFrame()
    placeholders_adj = ", ".join("?" * len(adjustments))
    placeholders_act = ", ".join("?" * len(activity_ids))
    return _q(
        con,
        f"""
        SELECT period_id, fiscal_year, quarter, period_start, period_end,
               has_four_quarters, activity_id, activity_label, activity_level,
               sort_order, adjustment, price_basis, measure, unit, value,
               source_file, source_sheet, source_table, source_cell
        FROM v_observation_current
        WHERE frequency = ? AND price_basis = ? AND measure = ?
          AND adjustment IN ({placeholders_adj})
          AND activity_id IN ({placeholders_act})
        ORDER BY period_start, sort_order, adjustment
        """,
        [frequency, price_basis, measure, *adjustments, *activity_ids],
    )


def snapshot(
    con,
    frequency: str,
    period_id: str,
    price_basis: str,
    adjustment: str,
    measure: str,
    activity_level: str,
) -> pd.DataFrame:
    """All activities at one hierarchy level for a single period.

    ``activity_level`` is always applied, so aggregates and their components can
    never appear in the same result set and cannot be double-counted.
    """
    return _q(
        con,
        """
        SELECT activity_id, activity_label, activity_level, parent_activity_id,
               isic_code, sort_order, value, unit,
               source_file, source_sheet, source_table, source_cell
        FROM v_observation_current
        WHERE frequency = ? AND period_id = ? AND price_basis = ?
          AND adjustment = ? AND measure = ? AND activity_level = ?
        ORDER BY sort_order
        """,
        [frequency, period_id, price_basis, adjustment, measure, activity_level],
    )


def observations(
    con,
    frequency: str | None = None,
    price_basis: str | None = None,
    adjustment: str | None = None,
    measure: str | None = None,
    activity_ids: list[str] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Filtered observation-level export, including full source lineage."""
    clauses, params = [], []
    for column, value in (
        ("frequency", frequency),
        ("price_basis", price_basis),
        ("adjustment", adjustment),
        ("measure", measure),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if activity_ids:
        clauses.append(f"activity_id IN ({', '.join('?' * len(activity_ids))})")
        params.extend(activity_ids)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    tail = f"LIMIT {int(limit)}" if limit else ""
    return _q(
        con,
        f"""
        SELECT period_id, frequency, fiscal_year, quarter, activity_label,
               activity_level, isic_code, price_basis, adjustment, measure,
               growth_basis, unit, value, release_id, release_date,
               source_file, source_sheet, source_table, source_cell, obs_id
        FROM v_observation_current
        {where}
        ORDER BY period_start DESC, sort_order
        {tail}
        """,
        params,
    )


def lineage(con, obs_id: str) -> pd.DataFrame:
    return _q(con, "SELECT * FROM v_lineage WHERE obs_id = ?", [obs_id])


# --------------------------------------------------------------------- qa ----

def reject_summary(con) -> pd.DataFrame:
    return _q(
        con,
        """
        SELECT reject_reason, in_scope, COUNT(*) AS cells,
               COUNT(DISTINCT source_file) AS files
        FROM stg_reject
        GROUP BY ALL
        ORDER BY cells DESC
        """,
    )


def coverage(con) -> pd.DataFrame:
    """Observation counts per release and series type - the 'what do I have' view."""
    return _q(
        con,
        """
        SELECT release_id, frequency, price_basis, adjustment, measure,
               COUNT(*) AS observations,
               MIN(period_id) AS first_period,
               MAX(period_id) AS last_period
        FROM v_observation_current
        GROUP BY ALL
        ORDER BY frequency, price_basis, adjustment, measure
        """,
    )
