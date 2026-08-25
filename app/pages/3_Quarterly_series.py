"""Quarterly series for one activity: original vs seasonally adjusted vs trend."""

from __future__ import annotations

import altair as alt
import streamlit as st

import _bootstrap as boot

boot.page("Quarterly series and seasonal adjustment")

price_basis, measure, adjustments = boot.pick_series(
    "Q", key="q", allow_multi_adjustment=True
)

acts = boot.activities().set_index("activity_id")
activity_id = st.sidebar.selectbox(
    "Activity",
    acts.index.tolist(),
    index=acts.index.tolist().index(boot.GDP_TOTAL),
    format_func=lambda a: f"{acts.label[a]}  ({acts.activity_level[a]})",
    key="q_activity",
)

periods = boot.periods("Q")
fy_options = periods.fiscal_year.unique().tolist()
fy_from, fy_to = st.sidebar.select_slider(
    "Fiscal year range",
    options=fy_options,
    value=(fy_options[max(0, len(fy_options) - 6)], fy_options[-1]),
    key="q_range",
)

if not adjustments:
    st.warning("Select at least one adjustment variant.")
    st.stop()

frame = boot.series("Q", price_basis, measure, tuple(adjustments), (activity_id,))
if frame.empty:
    st.warning("UBOS does not publish this combination.")
    st.stop()

keep = set(fy_options[fy_options.index(fy_from): fy_options.index(fy_to) + 1])
frame = frame[frame.fiscal_year.isin(keep)]

unit = frame.unit.iloc[0]
st.caption(
    f"**{acts.label[activity_id]}** - {boot.label_of('measure', measure)} - "
    f"{boot.label_of('price_basis', price_basis)}"
)

frame = frame.assign(Adjustment=frame.adjustment.map(lambda a: boot.label_of("adjustment", a)))
chart = (
    alt.Chart(frame)
    .mark_line(point=True)
    .encode(
        x=alt.X("period_id:O", title="Fiscal quarter", axis=alt.Axis(labelAngle=-60)),
        y=alt.Y("value:Q", title=boot.unit_label(unit), scale=alt.Scale(zero=False)),
        color=alt.Color("Adjustment:N", legend=alt.Legend(orient="top")),
        tooltip=[
            alt.Tooltip("period_id:N", title="Period"),
            alt.Tooltip("Adjustment:N"),
            alt.Tooltip("value:Q", title=boot.unit_label(unit), format=",.2f"),
            alt.Tooltip("period_start:T", title="Quarter starts"),
            alt.Tooltip("source_sheet:N", title="Sheet"),
            alt.Tooltip("source_cell:N", title="Cell"),
        ],
    )
    .properties(height=420)
)
st.altair_chart(chart, width="stretch")

boot.caveats(measure=measure, adjustments=adjustments)

partial = frame[~frame.has_four_quarters].fiscal_year.unique().tolist()
if partial:
    st.warning(
        boot.PARTIAL_FY_CAVEAT.format(fy=", ".join(partial)),
        icon=":material/warning:",
    )

if len(adjustments) > 1 and measure == "level":
    st.subheader("Seasonal pattern removed")
    wide = frame.pivot_table(
        index="period_id", columns="adjustment", values="value", sort=False
    )
    if "original" in wide and "seasonally_adjusted" in wide:
        diff = (wide["original"] - wide["seasonally_adjusted"]).reset_index(
            name="difference"
        )
        st.altair_chart(
            alt.Chart(diff)
            .mark_bar()
            .encode(
                x=alt.X("period_id:O", title=None, axis=alt.Axis(labelAngle=-60)),
                y=alt.Y("difference:Q", title="Original - seasonally adjusted"),
                color=alt.condition(
                    alt.datum.difference > 0,
                    alt.value("#4c78a8"),
                    alt.value("#e45756"),
                ),
                tooltip=[
                    alt.Tooltip("period_id:N", title="Period"),
                    alt.Tooltip("difference:Q", format=",.1f"),
                ],
            )
            .properties(height=200),
            width="stretch",
        )
        st.caption(
            "The seasonal component UBOS removed: positive bars are quarters that "
            "are seasonally strong for this activity."
        )

with st.expander("Table"):
    st.dataframe(
        frame[["period_id", "Adjustment", "value", "unit", "source_sheet", "source_cell"]],
        width="stretch",
        hide_index=True,
    )

boot.source_footer()
