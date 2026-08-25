"""Release-vintage resolution.

Every vintage is retained. The newest release for a given natural key is
flagged ``is_current``; nothing is deleted.
"""

from __future__ import annotations

import pandas as pd

# Natural key of an observation, excluding the release.
SERIES_KEY = [
    "frequency",
    "period_id",
    "activity_id",
    "price_basis",
    "adjustment",
    "measure",
]

# Relative difference above which two vintages are considered to disagree.
CONFLICT_TOLERANCE = 1e-6


def mark_current(frame: pd.DataFrame) -> pd.DataFrame:
    """Add ``is_current``: True for the latest ``release_date`` per series key."""
    latest = frame.groupby(SERIES_KEY, dropna=False)["release_date"].transform("max")
    frame = frame.copy()
    frame["is_current"] = frame["release_date"].eq(latest)
    return frame


def find_conflicts(frame: pd.DataFrame, tolerance: float = CONFLICT_TOLERANCE) -> pd.DataFrame:
    """Series keys whose value differs between release vintages.

    Significance is judged per unit: level series are compared on *relative*
    difference, percentage series on *absolute* difference in percentage points.
    Dividing a percentage-point change by a near-zero growth rate produces
    enormous, meaningless ratios, so ``rel_diff`` is reported for context but is
    not the test for percentage measures.
    """
    multi = frame.groupby(SERIES_KEY, dropna=False)["release_id"].transform("nunique")
    overlapping = frame[multi > 1]
    columns = SERIES_KEY + ["unit", "min_value", "max_value", "abs_diff", "rel_diff", "releases"]
    if overlapping.empty:
        return pd.DataFrame(columns=columns)
    grouped = overlapping.groupby(SERIES_KEY, dropna=False).agg(
        unit=("unit", "first"),
        min_value=("value", "min"),
        max_value=("value", "max"),
        releases=("release_id", lambda s: ",".join(sorted(set(s)))),
    )
    grouped["abs_diff"] = (grouped["max_value"] - grouped["min_value"]).abs()
    grouped["rel_diff"] = grouped["abs_diff"] / grouped["max_value"].abs().clip(lower=1e-12)
    is_pct = grouped["unit"].eq("pct")
    significant = (is_pct & (grouped["abs_diff"] > tolerance)) | (
        ~is_pct & (grouped["rel_diff"] > tolerance)
    )
    conflicts = grouped[significant].reset_index()
    return conflicts.sort_values("abs_diff", ascending=False)[columns]


def overlap_summary(frame: pd.DataFrame) -> dict:
    multi = frame.groupby(SERIES_KEY, dropna=False)["release_id"].transform("nunique")
    return {
        "series_keys_total": int(frame.groupby(SERIES_KEY, dropna=False).ngroups),
        "series_keys_multi_release": int(
            frame[multi > 1].groupby(SERIES_KEY, dropna=False).ngroups
        ),
        "rows_superseded": int((~frame["is_current"]).sum()),
    }
