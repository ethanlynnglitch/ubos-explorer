"""Shared app plumbing: import path, cached data access, UI helpers.

Imported first by every page. Streamlit puts the main script's directory on
sys.path, so `import _bootstrap` resolves from pages/ too.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ubos_explorer import queries  # noqa: E402

GDP_TOTAL = queries.GDP_TOTAL

# Caveats that must travel with the data wherever it is displayed.
GROWTH_CAVEAT = (
    "UBOS labels these tables only **\"PERCENTAGE CHANGE\"** and does not state "
    "whether the basis is year-on-year or quarter-on-quarter, so this dashboard "
    "does not claim either. `growth_basis` is recorded as unknown."
)
PARTIAL_FY_CAVEAT = (
    "Fiscal year **{fy}** has fewer than four published quarters, so its quarters "
    "must not be summed to a year total. The annual figure shown comes from the "
    "UBOS annual publication, not from summing quarters."
)
ADJUSTMENT_CAVEAT = (
    "Seasonally adjusted and trend-cycle series are **revised** when later "
    "quarters are published; the original (unadjusted) series is not."
)


def page(title: str, icon: str = "") -> None:
    st.set_page_config(page_title=f"{title} - UBOS GDP", layout="wide")
    st.title(title)


# ----------------------------------------------------------------- data access --

@st.cache_resource(show_spinner=False)
def _con():
    return queries.connect()


def con():
    """Cached read-only DuckDB connection, or a stop-the-page error."""
    try:
        return _con()
    except queries.WarehouseMissing as exc:
        st.error(str(exc))
        st.stop()


@st.cache_data(show_spinner=False)
def available_series() -> pd.DataFrame:
    return queries.available_series(con())


@st.cache_data(show_spinner=False)
def labels() -> dict:
    return queries.labels(con())


@st.cache_data(show_spinner=False)
def activities() -> pd.DataFrame:
    return queries.activities(con())


@st.cache_data(show_spinner=False)
def periods(frequency: str) -> pd.DataFrame:
    return queries.periods(con(), frequency)


@st.cache_data(show_spinner=False)
def headline() -> pd.DataFrame:
    return queries.headline(con())


@st.cache_data(show_spinner=False)
def series(frequency, price_basis, measure, adjustments, activity_ids) -> pd.DataFrame:
    return queries.series(
        con(), frequency, price_basis, measure, list(adjustments), list(activity_ids)
    )


@st.cache_data(show_spinner=False)
def snapshot(frequency, period_id, price_basis, adjustment, measure, level) -> pd.DataFrame:
    return queries.snapshot(
        con(), frequency, period_id, price_basis, adjustment, measure, level
    )


@st.cache_data(show_spinner=False)
def observations(**kwargs) -> pd.DataFrame:
    return queries.observations(con(), **kwargs)


@st.cache_data(show_spinner=False)
def source_blocks() -> pd.DataFrame:
    return queries.source_blocks(con())


@st.cache_data(show_spinner=False)
def reject_summary() -> pd.DataFrame:
    return queries.reject_summary(con())


@st.cache_data(show_spinner=False)
def coverage() -> pd.DataFrame:
    return queries.coverage(con())


@st.cache_data(show_spinner=False)
def build_info() -> pd.DataFrame:
    return queries.build_info(con())


# --------------------------------------------------------------- label helpers --

def label_of(attribute: str, code: str) -> str:
    return labels().get((attribute, code), (code, None))[0]


def note_of(attribute: str, code: str) -> str | None:
    return labels().get((attribute, code), (code, None))[1]


def unit_label(unit: str) -> str:
    return {"UGX_bn": "UGX billion", "pct": "%"}.get(unit, unit)


def fmt_value(value: float, unit: str) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.1f}" if unit == "UGX_bn" else f"{value:,.2f}%"


# ------------------------------------------------------------- filter widgets --

def pick_series(
    frequency: str,
    *,
    key: str,
    measure: str | None = None,
    allow_multi_adjustment: bool = False,
    sidebar: bool = True,
):
    """Cascading price-basis / measure / adjustment selectors.

    Options are derived from what actually exists in the warehouse, so an
    unavailable combination (e.g. current-price growth, which UBOS does not
    publish) can never be selected.
    """
    box = st.sidebar if sidebar else st
    avail = available_series()
    avail = avail[avail.frequency == frequency]

    if measure is None:
        # Levels first: the natural default view, and alphabetical order would
        # otherwise open every page on "growth".
        order = ["level", "growth_pct"]
        measures = sorted(avail.measure.unique(), key=lambda m: order.index(m)
                          if m in order else len(order))
        measure = box.radio(
            "Measure",
            measures,
            format_func=lambda m: label_of("measure", m),
            key=f"{key}_measure",
        )
    avail = avail[avail.measure == measure]

    bases = sorted(avail.price_basis.unique())
    price_basis = box.radio(
        "Price basis",
        bases,
        format_func=lambda b: label_of("price_basis", b),
        key=f"{key}_basis",
    )
    avail = avail[avail.price_basis == price_basis]

    adj_options = sorted(avail.adjustment.unique())
    if allow_multi_adjustment and len(adj_options) > 1:
        adjustments = box.multiselect(
            "Adjustment",
            adj_options,
            default=adj_options,
            format_func=lambda a: label_of("adjustment", a),
            key=f"{key}_adj",
        )
    elif len(adj_options) > 1:
        adjustments = [
            box.radio(
                "Adjustment",
                adj_options,
                format_func=lambda a: label_of("adjustment", a),
                key=f"{key}_adj",
            )
        ]
    else:
        adjustments = adj_options
        box.caption(f"Adjustment: {label_of('adjustment', adj_options[0])} (only option published)")

    return price_basis, measure, adjustments


def caveats(*, measure: str | None = None, adjustments: list[str] | None = None,
            partial_fy: str | None = None) -> None:
    """Render the caveats relevant to what is on screen."""
    notes = []
    if measure == "growth_pct":
        notes.append(GROWTH_CAVEAT)
    if adjustments and any(a != "original" for a in adjustments):
        notes.append(ADJUSTMENT_CAVEAT)
    if partial_fy:
        notes.append(PARTIAL_FY_CAVEAT.format(fy=partial_fy))
    for note in notes:
        st.caption(f":material/info: {note}")


def source_footer() -> None:
    st.divider()
    info = build_info()
    built = pd.to_datetime(info.built_at.iloc[0]).strftime("%Y-%m-%d %H:%M")
    st.caption(
        "Source: Uganda Bureau of Statistics GDP publications, extracted from the "
        "original workbooks with full cell-level lineage. "
        f"Warehouse built {built} - latest UBOS release only."
    )
