"""Write daily landing partitions: one Parquet file plus its manifest per day (System design §7.1).

Shared by every landing writer (prepare_local for the CSVs, fetch_weather for Open-Meteo), so all
sources get the same layout, the same atomic writes and the same manifests.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from rap_lakehouse.manifest import (
    PART_FILE,
    LandingManifest,
    partition_dir,
    sha256_file,
    write_manifest,
)


def days(start: date, end: date) -> list[date]:
    """Every calendar day from start to end, both included."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def copy_to_parquet(
    con: duckdb.DuckDBPyConnection, select_sql: str, params: dict, dest: Path
) -> int:
    """Write one query result to dest atomically; return the number of rows written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    rows = con.execute(
        f"COPY ({select_sql}) TO $dest (FORMAT parquet, COMPRESSION zstd)",
        params | {"dest": str(tmp)},
    ).fetchone()[0]
    os.replace(tmp, dest)
    return int(rows)


def write_partition(
    con: duckdb.DuckDBPyConnection,
    source: str,
    select_sql: str,
    params: dict,
    zone_root: Path,
    day: date,
    run_id: str,
) -> int:
    """Write one day's Parquet file, then its manifest; return the row count.

    The manifest goes last, so a crash can never leave a manifest describing a missing file.
    """
    part_dir = partition_dir(zone_root, source, day)
    rows = copy_to_parquet(con, select_sql, params, part_dir / PART_FILE)
    manifest = LandingManifest(
        source=source,
        business_date=day,
        row_count=rows,
        sha256=sha256_file(part_dir / PART_FILE),
        run_id=run_id,
        created_ts=datetime.now(UTC),
        injected=False,
    )
    write_manifest(part_dir, manifest)
    return rows
