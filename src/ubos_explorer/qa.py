"""Validation checks and the markdown QA report."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import vintage

ADDITIVITY_TOLERANCE = 0.005  # 0.5%

MAX_TABLE_ROWS = 40


def _md_table(frame: pd.DataFrame, max_rows: int = MAX_TABLE_ROWS) -> str:
    """Render a DataFrame as a GitHub markdown table without extra dependencies."""
    shown = frame.head(max_rows)
    columns = [str(c) for c in shown.columns]

    def fmt(value) -> str:
        if value is None or (isinstance(value, float) and value != value):
            return ""
        if isinstance(value, float):
            return f"{value:,.6g}"
        return str(value).replace("|", r"\|")

    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for _, row in shown.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in row.tolist()) + " |")
    if len(frame) > max_rows:
        lines.append(f"| _... {len(frame) - max_rows:,} more row(s) omitted_ |")
    return "\n".join(lines)


@dataclass
class Check:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str
    rows: pd.DataFrame | None = None


@dataclass
class QAResult:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str, rows: pd.DataFrame | None = None) -> None:
        self.checks.append(Check(name, status, detail, rows))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == "FAIL"]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.status == "WARN"]


def check_natural_key(obs: pd.DataFrame, result: QAResult) -> None:
    key = vintage.SERIES_KEY + ["release_id"]
    duplicated = obs[obs.duplicated(key, keep=False)]
    if duplicated.empty:
        result.add("natural_key_uniqueness", "PASS", f"{len(obs):,} rows, no duplicate keys")
    else:
        result.add(
            "natural_key_uniqueness",
            "FAIL",
            f"{len(duplicated):,} rows share a natural key",
            duplicated.sort_values(key).head(30),
        )


def check_unmapped_labels(unmapped: dict[str, list[str]], result: QAResult) -> None:
    if not unmapped:
        result.add("unmapped_activity_labels", "PASS", "every row label matched the crosswalk")
        return
    rows = pd.DataFrame(
        [{"source_id": sid, "label": lab} for sid, labs in unmapped.items() for lab in sorted(set(labs))]
    )
    result.add("unmapped_activity_labels", "FAIL", f"{len(rows)} unmatched label(s)", rows)


def check_periods(obs: pd.DataFrame, anomalies: list[dict], result: QAResult) -> None:
    bad = obs[
        ~obs["fiscal_year"].str.match(r"^\d{4}/\d{2}$")
        | (obs["frequency"].eq("Q") & ~obs["quarter"].isin([1, 2, 3, 4]))
        | (obs["frequency"].eq("A") & obs["quarter"].notna())
        | (obs["period_start"] >= obs["period_end"])
    ]
    if bad.empty:
        result.add(
            "period_validity",
            "PASS",
            f"{obs['period_id'].nunique()} distinct periods, all well formed",
        )
    else:
        result.add("period_validity", "FAIL", f"{len(bad):,} malformed periods", bad.head(30))

    if anomalies:
        frame = pd.DataFrame(anomalies)
        in_scope = frame[frame["message"].str.contains("IN SCOPE")]
        status = "FAIL" if not in_scope.empty else "WARN"
        result.add(
            "period_header_anomalies",
            status,
            f"{len(frame)} header anomaly/anomalies detected during parsing "
            f"({len(in_scope)} affecting in-scope fiscal years)",
            frame,
        )
    else:
        result.add("period_header_anomalies", "PASS", "no header anomalies detected")


def check_rejects(rejects: pd.DataFrame, result: QAResult) -> None:
    if rejects.empty:
        result.add("rejected_cells", "PASS", "no cells rejected")
        return
    summary = (
        rejects.groupby(["reject_reason", "in_scope"], dropna=False)
        .size()
        .reset_index(name="cells")
        .sort_values("cells", ascending=False)
    )
    in_scope_bad = rejects[
        rejects["in_scope"] & rejects["reject_reason"].isin(["error_cell", "non_numeric", "non_finite"])
    ]
    status = "WARN" if not in_scope_bad.empty else "PASS"
    detail = (
        f"{len(rejects):,} cells rejected; "
        f"{len(in_scope_bad):,} of them are error/non-numeric cells inside the in-scope period range"
    )
    result.add("rejected_cells", status, detail, summary)


def check_completeness(obs: pd.DataFrame, result: QAResult) -> None:
    """Every (block, period) should carry the full set of activity rows."""
    grouped = obs.groupby(["source_id", "period_id"], dropna=False)["activity_id"].nunique()
    expected = obs.groupby("source_id")["activity_id"].nunique()
    gaps = []
    for (source_id, period), count in grouped.items():
        if count != expected[source_id]:
            gaps.append(
                {
                    "source_id": source_id,
                    "period_id": period,
                    "activities": int(count),
                    "expected": int(expected[source_id]),
                }
            )
    if gaps:
        result.add(
            "missing_observations",
            "WARN",
            f"{len(gaps)} (block, period) combinations are short of activities",
            pd.DataFrame(gaps),
        )
    else:
        result.add(
            "missing_observations",
            "PASS",
            f"all {len(grouped)} (block, period) combinations carry the full activity set",
        )


def check_additivity(obs: pd.DataFrame, result: QAResult) -> None:
    """sectors + taxes == GDP, and components == their sector (levels only)."""
    levels = obs[obs["measure"].eq("level")]
    if levels.empty:
        result.add("additivity", "WARN", "no level observations to check")
        return
    group = ["release_id", "frequency", "period_id", "price_basis", "adjustment"]
    failures = []

    totals = levels[levels["activity_level"].eq("total")].set_index(group)["value"]
    sector_sum = (
        levels[levels["activity_level"].isin(["sector", "adjustment"])].groupby(group)["value"].sum()
    )
    joined = pd.concat([totals.rename("total"), sector_sum.rename("parts")], axis=1).dropna()
    joined["rel_diff"] = (joined["parts"] - joined["total"]).abs() / joined["total"].abs().clip(lower=1e-12)
    for key, row in joined[joined["rel_diff"] > ADDITIVITY_TOLERANCE].iterrows():
        failures.append({"scope": "sectors+taxes vs GDP", "key": " | ".join(map(str, key)), **row.to_dict()})

    parents = levels[levels["activity_level"].eq("sector")].set_index(group + ["activity_id"])["value"]
    children = (
        levels[levels["activity_level"].eq("activity")]
        .groupby(group + ["parent_activity_id"])["value"]
        .sum()
    )
    children.index.names = group + ["activity_id"]
    joined2 = pd.concat([parents.rename("total"), children.rename("parts")], axis=1).dropna()
    joined2["rel_diff"] = (joined2["parts"] - joined2["total"]).abs() / joined2["total"].abs().clip(lower=1e-12)
    for key, row in joined2[joined2["rel_diff"] > ADDITIVITY_TOLERANCE].iterrows():
        failures.append({"scope": "components vs sector", "key": " | ".join(map(str, key)), **row.to_dict()})

    checked = len(joined) + len(joined2)
    if failures:
        result.add(
            "additivity",
            "FAIL",
            f"{len(failures)} of {checked} additivity checks exceeded {ADDITIVITY_TOLERANCE:.1%}",
            pd.DataFrame(failures).sort_values("rel_diff", ascending=False).head(30),
        )
    else:
        result.add(
            "additivity",
            "PASS",
            f"all {checked} additivity checks within {ADDITIVITY_TOLERANCE:.1%}",
        )


def check_release_conflicts(obs: pd.DataFrame, result: QAResult) -> None:
    conflicts = vintage.find_conflicts(obs)
    summary = vintage.overlap_summary(obs)
    detail = (
        f"{summary['series_keys_multi_release']:,} series keys appear in more than one release; "
        f"{summary['rows_superseded']:,} rows flagged is_current=False"
    )
    if conflicts.empty:
        result.add("release_conflicts", "PASS", detail + "; no value disagreements", None)
        return
    by_series = (
        conflicts.groupby(["price_basis", "adjustment", "measure"])
        .agg(series_keys=("abs_diff", "size"), max_abs_diff=("abs_diff", "max"))
        .reset_index()
        .sort_values("series_keys", ascending=False)
    )
    result.add(
        "release_conflicts",
        "WARN",
        detail
        + f"; {len(conflicts):,} series revised between vintages "
        f"(levels judged on relative diff, percentages on absolute percentage points, "
        f"tolerance {vintage.CONFLICT_TOLERANCE:g})",
        by_series,
    )


def run_all(
    obs: pd.DataFrame,
    rejects: pd.DataFrame,
    unmapped: dict[str, list[str]],
    anomalies: list[dict],
) -> QAResult:
    result = QAResult()
    check_natural_key(obs, result)
    check_unmapped_labels(unmapped, result)
    check_periods(obs, anomalies, result)
    check_rejects(rejects, result)
    check_completeness(obs, result)
    check_additivity(obs, result)
    check_release_conflicts(obs, result)
    return result


def write_report(
    path: Path,
    result: QAResult,
    obs: pd.DataFrame,
    rejects: pd.DataFrame,
    blocks: pd.DataFrame,
) -> None:
    icon = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}
    lines: list[str] = []
    lines.append("# UBOS Explorer - Ingestion QA Report")
    lines.append("")
    lines.append(f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Source blocks processed: **{len(blocks)}**")
    lines.append(f"- Observations written: **{len(obs):,}**")
    lines.append(f"- Rejected cells: **{len(rejects):,}**")
    lines.append(f"- Current (non-superseded) observations: **{int(obs['is_current'].sum()):,}**")
    lines.append(f"- Checks failed: **{len(result.failed)}**, warnings: **{len(result.warned)}**")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| Check | Status | Detail |")
    lines.append("|---|---|---|")
    for check in result.checks:
        lines.append(f"| `{check.name}` | {icon[check.status]} | {check.detail} |")
    lines.append("")

    for check in result.checks:
        if check.rows is None or check.rows.empty:
            continue
        lines.append(f"### {check.name} ({check.status})")
        lines.append("")
        lines.append(_md_table(check.rows))
        lines.append("")

    lines.append("## Observations by release, frequency and measure")
    lines.append("")
    pivot = (
        obs.groupby(["release_id", "frequency", "price_basis", "adjustment", "measure"])
        .size()
        .reset_index(name="observations")
    )
    lines.append(_md_table(pivot, max_rows=100))
    lines.append("")

    lines.append("## Rejected cells by reason")
    lines.append("")
    if rejects.empty:
        lines.append("None.")
    else:
        summary = (
            rejects.groupby(["reject_reason", "in_scope"]).size().reset_index(name="cells")
        )
        lines.append(_md_table(summary))
    lines.append("")

    lines.append("## Source blocks")
    lines.append("")
    lines.append(
        _md_table(
            blocks[
                [
                    "source_id",
                    "source_file",
                    "source_sheet",
                    "source_table",
                    "engine",
                    "release_id",
                    "n_observations",
                    "n_rejects",
                ]
            ],
            max_rows=100,
        )
    )
    lines.append("")

    lines.append("## Known limitations")
    lines.append("")
    lines.append(
        "- `growth_basis` is deliberately **null** for every growth observation. "
        "The workbooks label these tables only \"PERCENTAGE CHANGE\" and do not state "
        "whether the change is year-on-year or quarter-on-quarter. This will remain "
        "unknown until it can be verified against authoritative UBOS documentation."
    )
    lines.append(
        "- The July-June fiscal-year convention used to derive `period_start`/`period_end` "
        "is an assumption (see `normalize.FY_START_MONTH`)."
    )
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
