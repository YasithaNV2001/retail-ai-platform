"""P1 step 1.3: split the Favorita CSVs into daily landing partitions with manifests (DuckDB).

For sales, transactions and oil, every calendar day from the source's first date to DATA_END
gets a partition, empty if the source has no rows that day:
  OUT/raw/SOURCE/business_date=D/   for D <= BACKFILL_END   (uploaded by the backfill)
  OUT/vault/SOURCE/business_date=D/ for D >  BACKFILL_END   (released one day per night)
Static reference files go to OUT/static/NAME/v1/NAME.parquet.
Every landed row gets _injected = false. Re-running rewrites the same files.

Run from p1-lakehouse/:
  uv run python landing/prepare_local.py
"""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
from retail_contracts.clock import BACKFILL_END, DATA_END

from rap_lakehouse.logs import setup_logging
from rap_lakehouse.manifest import (
    PART_FILE,
    LandingManifest,
    local_run_id,
    partition_dir,
    sha256_file,
    write_manifest,
)

log = logging.getLogger("prepare_local")

REPO_ROOT = Path(__file__).resolve().parents[2]
CITIES_CSV = REPO_ROOT / "contracts" / "config" / "cities.csv"

# Explicit column types (System design §6): IDs INT, quantities DOUBLE, flags BOOLEAN, dates DATE.
DAILY_SOURCES: dict[str, tuple[str, dict[str, str], str]] = {
    # source: (csv file, columns in file order, row order inside a partition)
    "sales": (
        "train.csv",
        {
            "id": "INTEGER",
            "date": "DATE",
            "store_nbr": "INTEGER",
            "item_nbr": "INTEGER",
            "unit_sales": "DOUBLE",
            "onpromotion": "BOOLEAN",
        },
        "store_nbr, item_nbr, id",
    ),
    "transactions": (
        "transactions.csv",
        {"date": "DATE", "store_nbr": "INTEGER", "transactions": "INTEGER"},
        "store_nbr",
    ),
    "oil": ("oil.csv", {"date": "DATE", "dcoilwtico": "DOUBLE"}, "date"),
}
STATIC_SOURCES: dict[str, tuple[str, dict[str, str]]] = {
    "items": (
        "items.csv",
        {
            "item_nbr": "INTEGER",
            "family": "VARCHAR",
            "class": "INTEGER",
            "perishable": "BOOLEAN",  # 0/1 in the CSV; a flag, so BOOLEAN (§6)
        },
    ),
    "stores": (
        "stores.csv",
        {
            "store_nbr": "INTEGER",
            "city": "VARCHAR",
            "state": "VARCHAR",
            "type": "VARCHAR",
            "cluster": "INTEGER",
        },
    ),
    "holidays": (
        "holidays_events.csv",
        {
            "date": "DATE",
            "type": "VARCHAR",
            "locale": "VARCHAR",
            "locale_name": "VARCHAR",
            "description": "VARCHAR",
            "transferred": "BOOLEAN",
        },
    ),
}
CITIES_COLUMNS = {
    "city": "VARCHAR",
    "state": "VARCHAR",
    "latitude": "DOUBLE",
    "longitude": "DOUBLE",
}


def columns_sql(columns: dict[str, str]) -> str:
    """DuckDB struct literal for read_csv(columns=...). Built only from the constants above."""
    return "{" + ", ".join(f"'{name}': '{typ}'" for name, typ in columns.items()) + "}"


def days(start: date, end: date) -> list[date]:
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


def land_daily_source(
    con: duckdb.DuckDBPyConnection,
    source: str,
    order_by: str,
    out: Path,
    run_id: str,
    backfill_end: date,
    data_end: date,
) -> dict[str, list[int]]:
    """Write one partition + manifest per day; return {"raw": [parts, rows], "vault": [...]}."""
    first = con.execute(f"SELECT min(date) FROM {source}").fetchone()[0]
    totals = {"raw": [0, 0], "vault": [0, 0]}
    for day in days(first, data_end):
        zone = "raw" if day <= backfill_end else "vault"
        part_dir = partition_dir(out / zone, source, day)
        rows = copy_to_parquet(
            con,
            f"SELECT *, false AS _injected FROM {source} WHERE date = $day ORDER BY {order_by}",
            {"day": day},
            part_dir / PART_FILE,
        )
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
        totals[zone][0] += 1
        totals[zone][1] += rows
    return totals


def prepare(
    favorita_dir: Path,
    out: Path,
    cities_csv: Path = CITIES_CSV,
    run_id: str | None = None,
    backfill_end: date = BACKFILL_END,
    data_end: date = DATA_END,
) -> dict[str, dict[str, list[int]]]:
    specs = [*DAILY_SOURCES.values(), *STATIC_SOURCES.values()]
    for path in [*(favorita_dir / spec[0] for spec in specs), cities_csv]:
        if not path.is_file():  # fail before minutes of work, not after
            raise FileNotFoundError(f"missing {path}; pass --favorita-dir or run step 1.2 first")
    run_id = run_id or local_run_id()
    out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, list[int]]] = {}
    # A throwaway DuckDB file next to the output: the CSVs are parsed once, then each day is a
    # cheap filtered read. Rows stay in file order (= date order), so min/max per row group
    # lets DuckDB skip everything but the requested day.
    with tempfile.TemporaryDirectory(dir=out.parent, prefix="prepare_local_") as work:
        con = duckdb.connect(str(Path(work) / "staging.duckdb"))
        con.execute("SET memory_limit = '4GB'")  # WSL has 10 GB; leave room for the rest
        con.execute("SET threads = 4")
        con.execute("SET temp_directory = $t", {"t": work})
        for source, (csv_name, columns, order_by) in DAILY_SOURCES.items():
            started = time.monotonic()
            con.execute(
                f"CREATE TABLE {source} AS SELECT * FROM read_csv($path, header = true, "
                f"columns = {columns_sql(columns)}) WHERE date <= $data_end",
                {"path": str(favorita_dir / csv_name), "data_end": data_end},
            )
            summary[source] = land_daily_source(
                con, source, order_by, out, run_id, backfill_end, data_end
            )
            log.info(
                "landed daily source",
                extra={
                    "source": source,
                    "raw_partitions": summary[source]["raw"][0],
                    "raw_rows": summary[source]["raw"][1],
                    "vault_partitions": summary[source]["vault"][0],
                    "vault_rows": summary[source]["vault"][1],
                    "seconds": round(time.monotonic() - started),
                },
            )
            con.execute(f"DROP TABLE {source}")
        statics = {name: (favorita_dir / f, cols) for name, (f, cols) in STATIC_SOURCES.items()}
        statics["cities"] = (cities_csv, CITIES_COLUMNS)
        for name, (path, columns) in statics.items():
            rows = copy_to_parquet(
                con,
                f"SELECT *, false AS _injected FROM read_csv($path, header = true, "
                f"columns = {columns_sql(columns)})",
                {"path": str(path)},
                out / "static" / name / "v1" / f"{name}.parquet",
            )
            log.info("landed static file", extra={"source": name, "rows": rows})
        con.close()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--favorita-dir", type=Path, default=Path.home() / "data" / "favorita")
    parser.add_argument("--out", type=Path, default=Path.home() / "data" / "rap" / "landing")
    args = parser.parse_args()
    run_id = local_run_id()
    setup_logging(run_id)
    log.info("start", extra={"backfill_end": BACKFILL_END, "data_end": DATA_END})
    summary = prepare(args.favorita_dir.expanduser(), args.out.expanduser(), run_id=run_id)
    sales_rows = summary["sales"]["raw"][1] + summary["sales"]["vault"][1]
    log.info("done", extra={"sales_rows": sales_rows})


if __name__ == "__main__":
    main()
