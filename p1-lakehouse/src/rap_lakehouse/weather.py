"""Open-Meteo historical archive: request, rate-limit handling and parsing into landing rows.

Weather for business date D always comes from the archive, never live weather (System design §5).
The backfill (landing/fetch_weather.py) and, later, the nightly job both use these functions.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date

import pyarrow as pa
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from rap_lakehouse.partitions import days

log = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "America/Guayaquil"  # daily values are local Ecuador days, like the sales dates
UNITS = {"temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm"}
# Free tier: 600 calls a minute, and a request longer than 2 weeks counts as several calls, so a
# multi-year backfill can hit the minute limit. On HTTP 429, wait for the window to reset.
RATE_LIMIT_WAIT_S = 61
MAX_RATE_LIMIT_WAITS = 5

# Landing columns: the API's daily variables under their own names, keyed by date and city.
WEATHER_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("city", pa.string()),
        ("state", pa.string()),
        ("temperature_2m_max", pa.float64()),
        ("temperature_2m_min", pa.float64()),
        ("precipitation_sum", pa.float64()),
    ]
)


def archive_params(latitude: float, longitude: float, start: date, end: date) -> dict[str, str]:
    return {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(UNITS),
        "timezone": TIMEZONE,
    }


def archive_session() -> requests.Session:
    """Retries connection errors and 5xx with backoff. 429 is handled by fetch_archive."""
    retry = Retry(total=4, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_archive(
    session: requests.Session,
    params: dict[str, str],
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """GET one archive response; wait out the per-minute limit instead of failing on 429."""
    for attempt in range(MAX_RATE_LIMIT_WAITS + 1):
        resp = session.get(ARCHIVE_URL, params=params, timeout=120)
        if resp.status_code != 429:
            break
        if attempt == MAX_RATE_LIMIT_WAITS:
            raise RuntimeError(f"Open-Meteo still rate-limiting: {resp.text[:200]}")
        log.warning("rate limited by Open-Meteo", extra={"wait_s": RATE_LIMIT_WAIT_S})
        sleep(RATE_LIMIT_WAIT_S)
    if resp.status_code == 400:  # the API explains bad parameters in a JSON "reason"
        raise ValueError(f"Open-Meteo rejected the request: {resp.json().get('reason')}")
    resp.raise_for_status()
    return resp.json()


def parse_daily(payload: dict, city: str, state: str, start: date, end: date) -> list[dict]:
    """One row per day, after checking that the response is exactly what was asked for."""
    if payload.get("timezone") != TIMEZONE:
        raise ValueError(f"{city}: timezone {payload.get('timezone')!r}, expected {TIMEZONE}")
    units = payload["daily_units"]
    for variable, unit in UNITS.items():
        if units.get(variable) != unit:
            raise ValueError(f"{city}: {variable} in {units.get(variable)!r}, expected {unit!r}")
    daily = payload["daily"]
    dates = [date.fromisoformat(t) for t in daily["time"]]
    if dates != days(start, end):
        raise ValueError(f"{city}: got {len(dates)} days, expected every day {start} to {end}")
    return [
        {"date": d, "city": city, "state": state} | {v: daily[v][i] for v in UNITS}
        for i, d in enumerate(dates)
    ]


def to_table(rows: list[dict]) -> pa.Table:
    """Typed Arrow table (§6: dates DATE, measures DOUBLE); null values stay null."""
    return pa.Table.from_pylist(rows, schema=WEATHER_SCHEMA)
