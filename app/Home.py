"""Overview page: headline GDP, annual trend, sector composition."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import _bootstrap as boot

boot.page("Uganda GDP - Overview")

head = boot.headline()
annual_levels = head[(head.frequency == "A") & (head.measure == "level")]
quarter_levels = head[(head.frequency == "Q") & (head.measure == "level")]
annual_growth = head[(head.frequency == "A") & (head.measure == "growth_pct")]

cols = st.columns(4)
for col, (_, row) in zip(cols, annual_levels.iterrows()):
    col.metric(
        f"GDP {row.fiscal_year} - {boot.label_of('price_basis', row.price_basis)}",
        boot.fmt_value(row.value, row.unit),
        help="Annual GDP at market prices, as published by UBOS.",
    )
if not annual_growth.empty:
    row = annual_growth.iloc[0]
    cols[2].metric(
        f"Real growth {row.fiscal_year}",
        boot.fmt_value(row.value, row.unit),
        help="Constant-price percentage change. Basis not stated by UBOS.",
    )
if not quarter_levels.empty:
    row = quarter_levels[quarter_levels.price_basis == "constant_2016_17"].iloc[0]
    cols[3].metric(
        f"Latest quarter ({row.period_id})",
        boot.fmt_value(row.value, row.unit),
        help="Constant-price, original (unadjusted) quarterly GDP.",
    )

st.divider()

# ------------------------------------------------------------ annual trend --
st.subheader("GDP by fiscal year")

trend = boot.series(
    frequency="A",
    price_basis="current",
    measure="level",
    adjustments=("original",),
    activity_ids=(boot.GDP_TOTAL,),
)
trend_k = boot.series(
    frequency="A",
    price_basis="constant_2016_17",
    measure="level",
    adjustments=("original",),
    activity_ids=(boot.GDP_TOTAL,),
)
both = pd.concat([trend, trend_k], ignore_index=True)
both["Price basis"] = both.price_basis.map(lambda b: boot.label_of("price_basis", b))

chart = (
    alt.Chart(both)
    .mark_line(point=True)
    .encode(
        x=alt.X("fiscal_year:O", title="Fiscal year"),
        y=alt.Y("value:Q", title="UGX billion", scale=alt.Scale(zero=False)),
        color=alt.Color("Price basis:N", legend=alt.Legend(orient="top")),
        tooltip=[
            alt.Tooltip("fiscal_year:O", title="Fiscal year"),
            alt.Tooltip("Price basis:N"),
            alt.Tooltip("value:Q", title="UGX bn", format=",.1f"),
            alt.Tooltip("source_sheet:N", title="Source sheet"),
            alt.Tooltip("source_cell:N", title="Cell"),
        ],
    )
    .properties(height=340)
)
st.altair_chart(chart, width="stretch")
st.caption(
    "The gap between the two lines is cumulative price change since the 2016/17 "
    "base year: current prices include inflation, constant prices do not."
)

# ------------------------------------------------------- sector composition --
st.subheader("Composition by sector")

periods = boot.periods("A")
latest_fy = periods.fiscal_year.iloc[-1]
left, right = st.columns([1, 3])
fy = left.selectbox(
    "Fiscal year", periods.fiscal_year.tolist()[::-1], index=0, key="home_fy"
)
basis = left.radio(
    "Price basis",
    ["current", "constant_2016_17"],
    format_func=lambda b: boot.label_of("price_basis", b),
    key="home_basis",
)

sectors = boot.snapshot("A", fy, basis, "original", "level", "sector")
if sectors.empty:
    right.info("No sector data published for this selection.")
else:
    total = sectors.value.sum()
    sectors = sectors.assign(share=lambda d: d.value / total * 100)
    pie = (
        alt.Chart(sectors)
        .mark_arc(innerRadius=60)
        .encode(
            theta=alt.Theta("value:Q", stack=True),
            color=alt.Color(
                "activity_label:N",
                title="Sector",
                sort=alt.EncodingSortField("sort_order"),
                legend=alt.Legend(orient="right"),
            ),
            tooltip=[
                alt.Tooltip("activity_label:N", title="Sector"),
                alt.Tooltip("value:Q", title="UGX bn", format=",.1f"),
                alt.Tooltip("share:Q", title="Share of sectors", format=".1f"),
                alt.Tooltip("source_cell:N", title="Cell"),
            ],
        )
        .properties(height=320)
    )
    right.altair_chart(pie, width="stretch")
    right.caption(
        "Sectors only (Agriculture, Industry, Services). Taxes on products are "
        "excluded here, so these shares sum to sector output rather than to GDP "
        "at market prices."
    )

st.info(
    "This dashboard shows the **latest UBOS release only**. Superseded release "
    "vintages are retained in the database but not displayed.",
    icon=":material/published_with_changes:",
)
boot.source_footer()
