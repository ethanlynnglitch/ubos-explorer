"""Growth over time, as published by UBOS (constant prices only)."""

from __future__ import annotations

import altair as alt
import streamlit as st

import _bootstrap as boot

boot.page("GDP growth over time")

frequency = st.sidebar.radio(
    "Frequency", ["A", "Q"], format_func=lambda f: {"A": "Annual", "Q": "Quarterly"}[f],
    key="gr_freq",
)
price_basis, measure, adjustments = boot.pick_series(
    frequency, key="gr", measure="growth_pct", allow_multi_adjustment=True
)

acts = boot.activities()
default = [boot.GDP_TOTAL] + acts[acts.activity_level == "sector"].activity_id.tolist()
chosen = st.sidebar.multiselect(
    "Activities",
    acts.activity_id.tolist(),
    default=default,
    format_func=lambda a: acts.set_index("activity_id").label[a],
    key="gr_acts",
)

st.info(boot.GROWTH_CAVEAT, icon=":material/help:")

if not chosen or not adjustments:
    st.warning("Select at least one activity and one adjustment.")
    st.stop()

frame = boot.series(frequency, price_basis, measure, tuple(adjustments), tuple(chosen))
if frame.empty:
    st.warning("UBOS does not publish growth for this combination.")
    st.stop()

x = (
    alt.X("fiscal_year:O", title="Fiscal year")
    if frequency == "A"
    else alt.X("period_id:O", title="Fiscal quarter", axis=alt.Axis(labelAngle=-60))
)

line = (
    alt.Chart(frame)
    .mark_line(point=len(frame.period_id.unique()) <= 12)
    .encode(
        x=x,
        y=alt.Y("value:Q", title="Percentage change (%)"),
        color=alt.Color(
            "activity_label:N",
            title="Activity",
            sort=alt.EncodingSortField("sort_order"),
        ),
        strokeDash=alt.StrokeDash("adjustment:N", title="Adjustment"),
        tooltip=[
            alt.Tooltip("period_id:N", title="Period"),
            alt.Tooltip("activity_label:N", title="Activity"),
            alt.Tooltip("adjustment:N"),
            alt.Tooltip("value:Q", title="% change", format=".2f"),
            alt.Tooltip("source_sheet:N", title="Sheet"),
            alt.Tooltip("source_cell:N", title="Cell"),
        ],
    )
    .properties(height=420)
)
zero = alt.Chart(frame).mark_rule(color="#888", strokeDash=[4, 4]).encode(y=alt.datum(0))
st.altair_chart(line + zero, width="stretch")

boot.caveats(adjustments=adjustments)

st.subheader("Latest published change")
latest = frame[frame.period_start == frame.period_start.max()]
cols = st.columns(min(4, max(1, len(latest))))
for col, (_, row) in zip(cols, latest.iterrows()):
    col.metric(
        f"{row.activity_label} ({row.period_id})",
        f"{row.value:,.2f}%",
        help=f"{boot.label_of('adjustment', row.adjustment)} - "
             f"{row.source_sheet}!{row.source_cell}",
    )

with st.expander("Table"):
    st.dataframe(
        frame[["period_id", "activity_label", "adjustment", "value", "unit",
               "source_sheet", "source_cell"]],
        width="stretch",
        hide_index=True,
    )

boot.source_footer()
