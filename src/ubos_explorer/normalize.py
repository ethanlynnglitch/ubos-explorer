"""Crosswalk lookup, period derivation and construction of fact rows."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .layouts import RawObservation, normalize_label

# Uganda's fiscal year runs July-June. This is an ASSUMPTION corroborated by the
# calendar-year header row of the UBOS expenditure sheets (FY 2016/17 spans
# calendar 2016 Q3/Q4 and 2017 Q1/Q2). It is deliberately implemented in one
# place so a correction touches one function.
FY_START_MONTH = 7


class UnmappedActivityLabel(Exception):
    """A row label had no entry in the activity crosswalk."""


@dataclass(frozen=True)
class Activity:
    activity_id: str
    label: str
    level: str
    parent_id: Optional[str]
    isic: Optional[str]


class ActivityCrosswalk:
    def __init__(self, path: Path):
        self.path = path
        self.by_id: dict[str, Activity] = {}
        self._by_key: dict[str, Activity] = {}
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                activity = Activity(
                    activity_id=row["activity_id"].strip(),
                    label=row["label"].strip(),
                    level=row["level"].strip(),
                    parent_id=row["parent_id"].strip() or None,
                    isic=row["isic"].strip() or None,
                )
                self.by_id[activity.activity_id] = activity
                aliases = [row["label"], row["alias_annual"], row["alias_quarterly"]]
                aliases += [a for a in row.get("alias_extra", "").split(";") if a.strip()]
                for alias in aliases:
                    key = normalize_label(alias)
                    if not key:
                        continue
                    existing = self._by_key.get(key)
                    if existing and existing.activity_id != activity.activity_id:
                        raise ValueError(
                            f"alias collision in {path.name}: {alias!r} maps to both "
                            f"{existing.activity_id} and {activity.activity_id}"
                        )
                    self._by_key[key] = activity

    def lookup(self, label: str) -> Activity:
        activity = self._by_key.get(normalize_label(label))
        if activity is None:
            raise UnmappedActivityLabel(label)
        return activity

    def __len__(self) -> int:
        return len(self.by_id)


def fy_start_year(fiscal_year: str) -> int:
    return int(fiscal_year[:4])


def period_bounds(fiscal_year: str, quarter: Optional[int]) -> tuple[dt.date, dt.date]:
    """Inclusive start/end dates for a fiscal year or fiscal quarter."""
    start_year = fy_start_year(fiscal_year)
    if quarter is None:
        return dt.date(start_year, FY_START_MONTH, 1), _month_end(
            start_year + 1, FY_START_MONTH - 1
        )
    offset = (quarter - 1) * 3
    month = FY_START_MONTH + offset
    year = start_year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    end_month_index = month + 2
    end_year = year + (end_month_index - 1) // 12
    end_month = (end_month_index - 1) % 12 + 1
    return dt.date(year, month, 1), _month_end(end_year, end_month)


def _month_end(year: int, month: int) -> dt.date:
    if month == 12:
        return dt.date(year, 12, 31)
    return dt.date(year, month + 1, 1) - dt.timedelta(days=1)


def period_id(fiscal_year: str, quarter: Optional[int]) -> str:
    return fiscal_year if quarter is None else f"{fiscal_year}Q{quarter}"


def make_obs_id(
    frequency: str,
    period: str,
    activity_id: str,
    price_basis: str,
    adjustment: str,
    measure: str,
    release_id: str,
) -> str:
    key = "|".join(
        [frequency, period, activity_id, price_basis, adjustment, measure, release_id]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def build_rows(
    observations: list[RawObservation],
    block: dict,
    crosswalk: ActivityCrosswalk,
) -> tuple[list[dict], list[str]]:
    """Turn raw observations into fact rows. Unmapped labels are collected."""
    rows: list[dict] = []
    unmapped: list[str] = []
    measure = block["measure"]
    for raw in observations:
        try:
            activity = crosswalk.lookup(raw.row_label)
        except UnmappedActivityLabel:
            unmapped.append(raw.row_label)
            continue
        period = period_id(raw.fiscal_year, raw.quarter)
        start, end = period_bounds(raw.fiscal_year, raw.quarter)
        rows.append(
            {
                "obs_id": make_obs_id(
                    block["frequency"],
                    period,
                    activity.activity_id,
                    block["price_basis"],
                    block["adjustment"],
                    measure,
                    block["release_id"],
                ),
                "frequency": block["frequency"],
                "fiscal_year": raw.fiscal_year,
                "fy_start_year": fy_start_year(raw.fiscal_year),
                "quarter": raw.quarter,
                "period_id": period,
                "period_start": start,
                "period_end": end,
                "activity_id": activity.activity_id,
                "activity_label": activity.label,
                "activity_level": activity.level,
                "parent_activity_id": activity.parent_id,
                # ISIC is only printed in the annual workbook; fall back to the
                # crosswalk so the column is populated consistently.
                "isic_code": raw.isic_code or activity.isic,
                "price_basis": block["price_basis"],
                "adjustment": block["adjustment"],
                "measure": measure,
                # UBOS labels these sheets only "PERCENTAGE CHANGE"; the basis
                # (year-on-year vs quarter-on-quarter) is NOT stated in the
                # workbooks and is left unknown until it can be verified against
                # authoritative UBOS documentation.
                "growth_basis": None,
                "unit": block["unit"],
                "value": raw.value,
                "release_id": block["release_id"],
                "release_date": block["release_date"],
                "source_id": block["source_id"],
                "source_file": block["file"],
                "source_sheet": block["sheet"],
                "source_table": block["source_table"],
                "source_cell": raw.cell,
            }
        )
    return rows, unmapped
