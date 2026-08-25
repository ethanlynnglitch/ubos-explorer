"""GDP by economic activity for a single period, at one hierarchy level."""

from __future__ import annotations

import altair as alt
import streamlit as st

import _bootstrap as boot

boot.page("GDP by economic activity")

frequency = st.sidebar.radio(
    "Frequency", ["A", "Q"], format_func=lambda f: {"A": "Annual", "Q": "Quarterly"}[f],
    key="act_freq",
)
price_basis, measure, adjustments = boot.pick_series(
    frequency, key="act", allow_multi_adjustment=False
)
adjustment = adjustments[0]

period_frame = boot.periods(frequency)
period_ids = period_frame.period_id.tolist()[::-1]
period_id = st.sidebar.selectbox("Period", period_ids, index=0, key="act_period")

level = st.sidebar.radio(
    "Hierarchy level",
    ["sector", "activity"],
    format_func=lambda x: {"sector": "Sectors (3)", "activity": "Activities (25)"}[x],
    key="act_level",
    help=(
        "Levels are shown one at a time on purpose: aggregates and their "
        "components coexist in the data, so mixing them would double-count."
    ),
)

frame = boot.snapshot(frequency, period_id, price_basis, adjustment, measure, level)

st.caption(
    f"**{boot.label_of('measure', measure)}** - "
    f"{boot.label_of('price_basis', price_basis)} - "
    f"{boot.label_of('adjustment', adjustment)} - **{period_id}**"
)

if frame.empty:
    st.warning("UBOS does not publish this combination. Try another selection.")
    st.stop()

unit = frame.unit.iloc[0]
sort_by = st.radio(
    "Order", ["Published order", "Largest first"], horizontal=True, key="act_sort"
)
order = (
    alt.EncodingSortField("sort_order", order="ascending")
    if sort_by == "Published order"
    else alt.EncodingSortField("value", order="descending")
)

bar = (
    alt.Chart(frame)
    .mark_bar()
    .encode(
        y=alt.Y("activity_label:N", title=None, sort=order),
        x=alt.X("value:Q", title=boot.unit_label(unit)),
        color=alt.Color(
            "value:Q", legend=None, scale=alt.Scale(scheme="blues")
        ),
        tooltip=[
            alt.Tooltip("activity_label:N", title="Activity"),
            alt.Tooltip("isic_code:N", title="ISIC"),
            alt.Tooltip("value:Q", title=boot.unit_label(unit), format=",.2f"),
            alt.Tooltip("source_file:N", title="Workbook"),
            alt.Tooltip("source_sheet:N", title="Sheet"),
            alt.Tooltip("source_cell:N", title="Cell"),
        ],
    )
    .properties(height=max(260, 26 * len(frame)))
)
st.altair_chart(bar, width="stretch")

boot.caveats(measure=measure, adjustments=[adjustment])

if measure == "level":
    total = frame.value.sum()
    st.caption(
        f"Sum of the {len(frame)} rows shown: **{total:,.1f} UGX bn**. "
        + (
            "Sectors plus taxes on products reconcile to GDP at market prices."
            if level == "sector"
            else "Components sum to their parent sector, not to GDP directly."
        )
    )

with st.expander("Table"):
    display = frame[
        ["activity_label", "activity_level", "isic_code", "value", "unit",
         "source_sheet", "source_cell"]
    ].rename(columns={"activity_label": "Activity", "value": boot.unit_label(unit)})
    st.dataframe(display, width="stretch", hide_index=True)

boot.source_footer()
