"""The two approved layout parsers.

``quarterly_va``  - quarterly GDP-by-activity sheets (both price bases, all
                    three seasonal-adjustment variants).
``annual_isic``   - annual publication tables with an ISIC code column.

Both return raw, un-normalised records plus every cell that was refused, so
that nothing is silently discarded. Neither parser knows anything about the
Excel engine in use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .io_excel import CellError, Sheet, cell_ref

FISCAL_YEAR = re.compile(r"^\d{4}/\d{2}$")
QUARTERS = ("Q1", "Q2", "Q3", "Q4")


@dataclass
class RawObservation:
    row_label: str
    fiscal_year: str
    quarter: Optional[int]
    value: float
    isic_code: Optional[str]
    row: int
    col: int
    cell: str


@dataclass
class Reject:
    row_label: str
    fiscal_year: Optional[str]
    quarter: Optional[int]
    raw_value: str
    reject_reason: str
    in_scope: bool
    row: int
    col: int
    cell: str


@dataclass
class PeriodColumn:
    col: int
    fiscal_year: str
    quarter: Optional[int]


@dataclass
class BlockResult:
    observations: list[RawObservation] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)
    period_columns: list[PeriodColumn] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    title: str = ""


def normalize_label(text: str) -> str:
    """Aggressive label key: casefold, ``&``->``and``, drop non-alphanumerics.

    Absorbs every label variant observed across the workbooks, e.g.
    ``AGRICULTURE,FORESTRY&FISHING`` and ``Agriculture, forestry and fishing``
    both collapse to ``agricultureforestryandfishing``.
    """
    lowered = text.replace("&", " and ").casefold()
    return re.sub(r"[^a-z0-9]+", "", lowered)


def _fy_start_year(fiscal_year: str) -> int:
    return int(fiscal_year[:4])


def _iter_data_rows(data_rows: list[list[int]]):
    for start, end in data_rows:
        yield from range(start, end + 1)


def _classify(value: Any) -> tuple[Optional[float], Optional[str], str]:
    """-> (numeric value, reject reason, raw text)."""
    if value is None:
        return None, "blank", ""
    if isinstance(value, CellError):
        return None, "error_cell", str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None, "non_finite", repr(value)
        return value, None, repr(value)
    return None, "non_numeric", str(value)


def _collect(
    sheet: Sheet,
    columns: list[PeriodColumn],
    rows: list[int],
    label_col: int,
    skip_keys: set[str],
    min_fy_start: int,
    result: BlockResult,
    isic_col: Optional[int] = None,
) -> None:
    """Shared cell walk used by both layouts."""
    for row in rows:
        label = sheet.text(row, label_col)
        if not label or normalize_label(label) in skip_keys:
            continue  # structural row (blank spacer or section heading)
        isic = sheet.text(row, isic_col) if isic_col else ""
        for column in columns:
            in_scope = _fy_start_year(column.fiscal_year) >= min_fy_start
            ref = cell_ref(row, column.col)
            number, reason, raw = _classify(sheet.cell(row, column.col))
            if reason is None and not in_scope:
                reason = "out_of_scope_period"
            if reason is not None:
                result.rejects.append(
                    Reject(
                        row_label=label,
                        fiscal_year=column.fiscal_year,
                        quarter=column.quarter,
                        raw_value=raw,
                        reject_reason=reason,
                        in_scope=in_scope,
                        row=row,
                        col=column.col,
                        cell=ref,
                    )
                )
                continue
            result.observations.append(
                RawObservation(
                    row_label=label,
                    fiscal_year=column.fiscal_year,
                    quarter=column.quarter,
                    value=number,
                    isic_code=isic or None,
                    row=row,
                    col=column.col,
                    cell=ref,
                )
            )


def _check_period_columns(columns: list[PeriodColumn], min_fy_start: int) -> list[str]:
    """Structural sanity checks on the reconstructed period axis."""
    anomalies: list[str] = []
    seen: dict[tuple[str, Optional[int]], int] = {}
    for column in columns:
        key = (column.fiscal_year, column.quarter)
        if key in seen:
            scope = "IN SCOPE" if _fy_start_year(column.fiscal_year) >= min_fy_start else "out of scope"
            anomalies.append(
                f"duplicate period column {key[0]}"
                f"{'Q%d' % key[1] if key[1] else ''} at columns "
                f"{seen[key]} and {column.col} ({scope})"
            )
        else:
            seen[key] = column.col
    quarters_by_fy: dict[str, list[int]] = {}
    for column in columns:
        if column.quarter is not None:
            quarters_by_fy.setdefault(column.fiscal_year, []).append(column.quarter)
    if quarters_by_fy:
        # The first and last fiscal year of a series are legitimately partial.
        interior = sorted(quarters_by_fy)[1:-1]
        for fiscal_year in interior:
            quarters = sorted(quarters_by_fy[fiscal_year])
            if quarters != [1, 2, 3, 4]:
                scope = (
                    "IN SCOPE"
                    if _fy_start_year(fiscal_year) >= min_fy_start
                    else "out of scope"
                )
                anomalies.append(
                    f"fiscal year {fiscal_year} has quarters {quarters} "
                    f"instead of [1, 2, 3, 4] ({scope})"
                )
    return anomalies


def quarterly_va(sheet: Sheet, block: dict, layout: dict, min_fiscal_year: str) -> BlockResult:
    """Parse a quarterly GDP-by-activity sheet.

    The period axis is rebuilt from two header rows: the fiscal year (row 3,
    merged across its quarters in most workbooks but repeated per column in the
    June constant-price workbook) and the quarter (row 4).

    A column is accepted only when the forward-filled fiscal year matches
    ``YYYY/YY`` *and* the quarter cell is one of Q1..Q4. That rule alone
    excludes the stray block of annual totals in columns B-F of
    ``06_2026QGDP_Constant_Prices_Q3_2025-26.xlsx``, whose quarter row holds
    fiscal-year strings rather than quarter labels.
    """
    result = BlockResult()
    year_row = layout["year_row"]
    quarter_row = layout["quarter_row"]
    label_col = layout["label_col"]
    first_col = block.get("first_data_col", label_col + 1)
    min_fy_start = _fy_start_year(min_fiscal_year)

    title_row, title_col = block.get("title_cell", [1, 1])
    result.title = sheet.text(title_row, title_col)

    current_fy: Optional[str] = None
    for col in range(label_col + 1, sheet.n_cols + 1):
        year_text = sheet.text(year_row, col)
        if year_text:
            current_fy = year_text  # forward-fill across merged/blank cells
        if col < first_col:
            continue
        quarter_text = sheet.text(quarter_row, col)
        if quarter_text not in QUARTERS:
            continue
        if not current_fy or not FISCAL_YEAR.match(current_fy):
            continue
        result.period_columns.append(
            PeriodColumn(col=col, fiscal_year=current_fy, quarter=int(quarter_text[1]))
        )

    result.anomalies = _check_period_columns(result.period_columns, min_fy_start)
    skip_keys = {normalize_label(x) for x in layout.get("skip_labels", [])}
    _collect(
        sheet,
        result.period_columns,
        list(_iter_data_rows(block.get("data_rows", layout["data_rows"]))),
        label_col,
        skip_keys,
        min_fy_start,
        result,
    )
    return result


def annual_isic(sheet: Sheet, block: dict, layout: dict, min_fiscal_year: str) -> BlockResult:
    """Parse one annual publication-table block (labels in B, ISIC in C)."""
    result = BlockResult()
    label_col = layout["label_col"]
    isic_col = layout["isic_col"]
    first_col = block.get("first_data_col", layout["first_data_col"])
    year_row = block["year_row"]
    min_fy_start = _fy_start_year(min_fiscal_year)

    title_row, title_col = block["title_cell"]
    result.title = " / ".join(
        part
        for part in (
            sheet.text(title_row, title_col),
            sheet.text(title_row + 1, title_col),
            sheet.text(title_row + 2, title_col),
        )
        if part
    )

    for col in range(first_col, sheet.n_cols + 1):
        year_text = sheet.text(year_row, col)
        if FISCAL_YEAR.match(year_text):
            result.period_columns.append(
                PeriodColumn(col=col, fiscal_year=year_text, quarter=None)
            )

    result.anomalies = _check_period_columns(result.period_columns, min_fy_start)
    skip_keys = {normalize_label(x) for x in layout.get("skip_labels", [])}
    _collect(
        sheet,
        result.period_columns,
        list(_iter_data_rows(block["data_rows"])),
        label_col,
        skip_keys,
        min_fy_start,
        result,
        isic_col=isic_col,
    )
    return result


PARSERS = {"quarterly_va": quarterly_va, "annual_isic": annual_isic}
