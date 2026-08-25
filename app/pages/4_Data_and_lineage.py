"""Observation-level browser, source lineage and ingestion QA."""

from __future__ import annotations

import streamlit as st

import _bootstrap as boot

boot.page("Data, source lineage and QA")


def _describe(frame, obs_id: str) -> str:
    row = frame[frame.obs_id == obs_id].iloc[0]
    return f"{row.period_id} - {row.activity_label} - {row.value:,.2f} {row.unit}"

tab_data, tab_sources, tab_qa = st.tabs(
    ["Observations", "Source workbooks", "Ingestion QA"]
)

# --------------------------------------------------------------- observations --
with tab_data:
    st.caption(
        "Every row carries the workbook, worksheet, published table and exact "
        "cell it came from, so any figure can be checked against the original "
        "UBOS file."
    )
    avail = boot.available_series()
    c1, c2, c3, c4 = st.columns(4)
    frequency = c1.selectbox(
        "Frequency", ["A", "Q"],
        format_func=lambda f: {"A": "Annual", "Q": "Quarterly"}[f], key="d_freq",
    )
    subset = avail[avail.frequency == frequency]
    price_basis = c2.selectbox(
        "Price basis", sorted(subset.price_basis.unique()),
        format_func=lambda b: boot.label_of("price_basis", b), key="d_basis",
    )
    subset = subset[subset.price_basis == price_basis]
    measure = c3.selectbox(
        "Measure", sorted(subset.measure.unique()),
        format_func=lambda m: boot.label_of("measure", m), key="d_measure",
    )
    subset = subset[subset.measure == measure]
    adjustment = c4.selectbox(
        "Adjustment", sorted(subset.adjustment.unique()),
        format_func=lambda a: boot.label_of("adjustment", a), key="d_adj",
    )

    acts = boot.activities().set_index("activity_id")
    chosen = st.multiselect(
        "Activities (all if empty)", acts.index.tolist(),
        format_func=lambda a: acts.label[a], key="d_acts",
    )

    frame = boot.observations(
        frequency=frequency,
        price_basis=price_basis,
        measure=measure,
        adjustment=adjustment,
        activity_ids=chosen or None,
    )
    st.write(f"**{len(frame):,}** observations")
    st.dataframe(frame, width="stretch", hide_index=True, height=420)
    st.download_button(
        "Download this selection as CSV",
        frame.to_csv(index=False).encode("utf-8"),
        file_name="ubos_gdp_selection.csv",
        mime="text/csv",
    )

    if not frame.empty:
        st.subheader("Trace one observation")
        obs_id = st.selectbox(
            "Observation",
            frame.obs_id.tolist()[:500],
            format_func=lambda o: _describe(frame, o),
            key="d_obs",
        )
        detail = boot.con().cursor().execute(
            "SELECT * FROM v_lineage WHERE obs_id = ?", [obs_id]
        ).df()
        # Transposing mixes types within one column, which Arrow cannot encode,
        # so render the lineage as text field/value pairs.
        pairs = detail.T.reset_index()
        pairs.columns = ["field", "value"]
        pairs["value"] = pairs["value"].astype(str)
        st.dataframe(pairs, width="stretch", hide_index=True)

# ------------------------------------------------------------------ sources --
with tab_sources:
    st.caption(
        "The 21 extracted table blocks. `file_sha256` pins the exact workbook "
        "bytes each block was read from."
    )
    st.dataframe(boot.source_blocks(), width="stretch", hide_index=True)

    st.subheader("Coverage")
    st.dataframe(boot.coverage(), width="stretch", hide_index=True)

# ----------------------------------------------------------------------- qa --
with tab_qa:
    st.caption(
        "Cells that did not become observations. Nothing is discarded silently: "
        "every refusal is recorded with a reason."
    )
    st.dataframe(boot.reject_summary(), width="stretch", hide_index=True)
    st.markdown(
        """
**How to read this**

- `out_of_scope_period` - pre-2016/17 back series, deliberately outside MVP scope.
- `error_cell` - cached Excel errors (`#DIV/0!`, `#REF!`) in the source workbook.
- `blank` - empty cells inside an otherwise valid table.

All three occur only outside the in-scope period range: no in-scope cell was
rejected, which is why the fact table is complete for 2016/17 onward.
        """
    )
    st.subheader("Warehouse build")
    st.dataframe(boot.build_info(), width="stretch", hide_index=True)

boot.source_footer()
