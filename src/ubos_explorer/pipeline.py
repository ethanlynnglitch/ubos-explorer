"""Ingestion pipeline entry point.

Reads the configured source blocks out of the untouched workbooks in
``data/raw/`` and writes a validated, traceable Parquet representation to
``data/processed/``:

* ``gdp_observations.parquet``  - the fact table (all vintages, ``is_current`` flag)
* ``source_blocks.parquet``     - extraction manifest with file hashes
* ``rejects.parquet``           - every cell that did not become an observation

Usage::

    python -m ubos_explorer.pipeline
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import yaml

from . import qa, vintage
from .io_excel import file_sha256, open_workbook
from .layouts import PARSERS
from .normalize import ActivityCrosswalk, build_rows

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]

OBSERVATION_COLUMNS = [
    "obs_id",
    "frequency",
    "fiscal_year",
    "fy_start_year",
    "quarter",
    "period_id",
    "period_start",
    "period_end",
    "activity_id",
    "activity_label",
    "activity_level",
    "parent_activity_id",
    "isic_code",
    "price_basis",
    "adjustment",
    "measure",
    "growth_basis",
    "unit",
    "value",
    "release_id",
    "release_date",
    "is_current",
    "source_id",
    "source_file",
    "source_sheet",
    "source_table",
    "source_cell",
]


def _as_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def extract(config: dict, raw_dir: Path, crosswalk: ActivityCrosswalk):
    min_fiscal_year = config["scope"]["min_fiscal_year"]
    layouts = config["layouts"]

    rows: list[dict] = []
    rejects: list[dict] = []
    manifest: list[dict] = []
    unmapped: dict[str, list[str]] = {}
    anomalies: list[dict] = []
    workbooks: dict[str, object] = {}
    hashes: dict[str, str] = {}

    try:
        for block in config["blocks"]:
            path = raw_dir / block["file"]
            if not path.exists():
                raise FileNotFoundError(f"source workbook missing: {path}")
            if block["file"] not in workbooks:
                workbooks[block["file"]] = open_workbook(path, block["engine"])
                hashes[block["file"]] = file_sha256(path)
            workbook = workbooks[block["file"]]
            sheet = workbook.sheet(block["sheet"])
            layout = layouts[block["layout"]]

            block = dict(block)
            block["release_date"] = _as_date(block["release_date"])

            result = PARSERS[block["layout"]](sheet, block, layout, min_fiscal_year)

            block_rows, block_unmapped = build_rows(result.observations, block, crosswalk)
            if block_unmapped:
                unmapped[block["source_id"]] = block_unmapped
            rows.extend(block_rows)

            for reject in result.rejects:
                rejects.append(
                    {
                        "source_id": block["source_id"],
                        "source_file": block["file"],
                        "source_sheet": block["sheet"],
                        "source_table": block["source_table"],
                        "source_cell": reject.cell,
                        "row": reject.row,
                        "col": reject.col,
                        "row_label": reject.row_label,
                        "fiscal_year": reject.fiscal_year,
                        "quarter": reject.quarter,
                        "raw_value": reject.raw_value,
                        "reject_reason": reject.reject_reason,
                        "in_scope": reject.in_scope,
                        "release_id": block["release_id"],
                    }
                )

            for message in result.anomalies:
                anomalies.append(
                    {
                        "source_id": block["source_id"],
                        "source_sheet": block["sheet"],
                        "message": message,
                    }
                )

            period_cols = result.period_columns
            manifest.append(
                {
                    "source_id": block["source_id"],
                    "source_file": block["file"],
                    "file_sha256": hashes[block["file"]],
                    "source_sheet": block["sheet"],
                    "source_table": block["source_table"],
                    "table_title": result.title,
                    "engine": block["engine"],
                    "layout": block["layout"],
                    "header_rows": _header_rows(block, layout),
                    "data_rows": str(block.get("data_rows", layout.get("data_rows"))),
                    "data_cols": (
                        f"{period_cols[0].col}-{period_cols[-1].col}" if period_cols else ""
                    ),
                    "period_columns_found": len(period_cols),
                    "frequency": block["frequency"],
                    "price_basis": block["price_basis"],
                    "adjustment": block["adjustment"],
                    "measure": block["measure"],
                    "unit": block["unit"],
                    "release_id": block["release_id"],
                    "release_date": block["release_date"],
                    "extracted_at": dt.datetime.now(),
                    "n_observations": len(block_rows),
                    "n_rejects": len(result.rejects),
                }
            )
    finally:
        for workbook in workbooks.values():
            workbook.close()

    return rows, rejects, manifest, unmapped, anomalies


def _header_rows(block: dict, layout: dict) -> str:
    if block["layout"] == "quarterly_va":
        return f"year_row={layout['year_row']},quarter_row={layout['quarter_row']}"
    return f"year_row={block['year_row']}"


def to_observation_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["quarter"] = frame["quarter"].astype("Int8")
    frame["fy_start_year"] = frame["fy_start_year"].astype("int16")
    frame["period_start"] = pd.to_datetime(frame["period_start"])
    frame["period_end"] = pd.to_datetime(frame["period_end"])
    frame["release_date"] = pd.to_datetime(frame["release_date"])
    frame["value"] = frame["value"].astype("float64")
    frame["growth_basis"] = pd.Series([None] * len(frame), dtype="object")
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest UBOS GDP workbooks to Parquet.")
    parser.add_argument("--raw-dir", type=Path, default=PROJECT_ROOT / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "data" / "processed")
    parser.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--config", type=Path, default=PACKAGE_DIR / "config" / "sources.yml")
    parser.add_argument(
        "--activities", type=Path, default=PACKAGE_DIR / "config" / "activities.csv"
    )
    args = parser.parse_args(argv)

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    crosswalk = ActivityCrosswalk(args.activities)
    print(f"crosswalk       : {len(crosswalk)} activities from {args.activities.name}")
    print(f"source blocks   : {len(config['blocks'])} configured")
    print(f"raw directory   : {args.raw_dir} (read-only)")

    rows, rejects, manifest, unmapped, anomalies = extract(config, args.raw_dir, crosswalk)

    if unmapped:
        print("\nERROR: unmatched activity labels (nothing written):", file=sys.stderr)
        for source_id, labels in unmapped.items():
            for label in sorted(set(labels)):
                print(f"  {source_id}: {label!r}", file=sys.stderr)
        return 2

    observations = to_observation_frame(rows)
    observations = vintage.mark_current(observations)
    observations = observations[OBSERVATION_COLUMNS]

    reject_frame = pd.DataFrame(rejects)
    manifest_frame = pd.DataFrame(manifest)

    result = qa.run_all(observations, reject_frame, unmapped, anomalies)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    observations.to_parquet(args.out_dir / "gdp_observations.parquet", index=False)
    reject_frame.to_parquet(args.out_dir / "rejects.parquet", index=False)
    manifest_frame.to_parquet(args.out_dir / "source_blocks.parquet", index=False)
    qa.write_report(
        args.reports_dir / "ingestion_qa.md", result, observations, reject_frame, manifest_frame
    )

    print(f"\nblocks processed: {len(manifest_frame)}")
    print(f"observations    : {len(observations):,} ({int(observations['is_current'].sum()):,} current)")
    print(f"rejects         : {len(reject_frame):,}")
    print("\nvalidation:")
    for check in result.checks:
        print(f"  [{check.status}] {check.name}: {check.detail}")
    print(f"\nwrote {args.out_dir}/gdp_observations.parquet")
    print(f"wrote {args.out_dir}/source_blocks.parquet")
    print(f"wrote {args.out_dir}/rejects.parquet")
    print(f"wrote {args.reports_dir}/ingestion_qa.md")

    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
