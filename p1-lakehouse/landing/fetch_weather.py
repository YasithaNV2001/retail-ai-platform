"""P1 step 1.4: Open-Meteo archive to daily weather partitions, one row per city per day.

One archive request per city covers the whole range. Each raw response is saved to the cache
before it is parsed, so a rerun never calls the API again for the same city and range.
  OUT/raw/weather/business_date=D/   part-0000.parquet + _manifest.json, one row per city
  CACHE/CITY_START_END.json          the raw API responses

Run from p1-lakehouse/:
  uv run python landing/fetch_weather.py
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path

import duckdb
from retail_contracts.clock import BACKFILL_END, DATA_END

from rap_lakehouse.logs import setup_logging
from rap_lakehouse.manifest import local_run_id
from rap_lakehouse.partitions import days, write_partition
from rap_lakehouse.weather import (
    archive_params,
    archive_session,
    fetch_archive,
    parse_daily,
    to_table,
)

log = logging.getLogger("fetch_weather")

REPO_ROOT = Path(__file__).resolve().parents[2]
CITIES_CSV = REPO_ROOT / "contracts" / "config" / "cities.csv"
FIRST_DAY = date(2013, 1, 1)  # first business date in the landing zone (step 1.3)
PAUSE_S = 1.0  # P1 spec: pause a second between requests


def read_cities(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        cities = list(csv.DictReader(f))
    names = [c["city"] for c in cities]
    if len(set(names)) != len(names):  # gold.fact_weather_daily is keyed by date and city
        raise ValueError(f"duplicate city names in {path}")
    return cities


def cache_path(cache_dir: Path, city: str, start: date, end: date) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
    return cache_dir / f"{slug}_{start.isoformat()}_{end.isoformat()}.json"


def load_or_fetch(
    path: Path, params: dict[str, str], fetch: Callable[[dict[str, str]], dict]
) -> tuple[dict, bool]:
    """Return (payload, fetched). A cached response is reused; a new one is saved atomically."""
    if path.is_file():
        return json.loads(path.read_text("utf-8")), False
    payload = fetch(params)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)
    return payload, True


def land_weather(
    cities_csv: Path,
    out: Path,
    cache_dir: Path,
    start: date,
    end: date,
    run_id: str,
    fetch: Callable[[dict[str, str]], dict],
    pause_s: float = PAUSE_S,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fetch (or reuse) every city's range, then write one raw partition per day."""
    rows: list[dict] = []
    for city in read_cities(cities_csv):
        params = archive_params(float(city["latitude"]), float(city["longitude"]), start, end)
        path = cache_path(cache_dir, city["city"], start, end)
        payload, fetched = load_or_fetch(path, params, fetch)
        try:
            rows += parse_daily(payload, city["city"], city["state"], start, end)
        except ValueError as err:  # a bad response is cached too, so say how to refetch it
            raise ValueError(f"{err} (response cached at {path}; delete it to refetch)") from err
        log.info("city ready", extra={"city": city["city"], "from_cache": not fetched})
        if fetched:
            sleep(pause_s)
    con = duckdb.connect()  # in memory: about 30,000 rows for the whole backfill
    con.register("weather", to_table(rows))
    for day in days(start, end):
        write_partition(
            con,
            "weather",
            "SELECT *, false AS _injected FROM weather WHERE date = $day ORDER BY city",
            {"day": day},
            out / "raw",
            day,
            run_id,
        )
    con.close()
    return len(days(start, end))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, default=FIRST_DAY)
    parser.add_argument("--end", type=date.fromisoformat, default=BACKFILL_END)
    parser.add_argument("--out", type=Path, default=Path.home() / "data" / "rap" / "landing")
    parser.add_argument(
        "--cache-dir", type=Path, default=Path.home() / "data" / "rap" / "cache" / "open-meteo"
    )
    args = parser.parse_args()
    if not args.start <= args.end <= DATA_END:
        parser.error(f"need --start <= --end <= {DATA_END} (the clock never releases later days)")
    run_id = local_run_id()
    setup_logging(run_id)
    log.info("start", extra={"start": args.start, "end": args.end})
    partitions = land_weather(
        CITIES_CSV,
        args.out.expanduser(),
        args.cache_dir.expanduser(),
        args.start,
        args.end,
        run_id,
        fetch=partial(fetch_archive, archive_session()),
    )
    log.info("done", extra={"partitions": partitions})


if __name__ == "__main__":
    main()
