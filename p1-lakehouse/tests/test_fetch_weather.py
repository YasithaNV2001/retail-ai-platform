"""fetch_weather on two synthetic cities and three days, with a fake API and no network."""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

import fetch_weather as fw
from rap_lakehouse.manifest import read_manifest, sha256_file
from rap_lakehouse.partitions import days
from rap_lakehouse.weather import TIMEZONE, UNITS

START, END = date(2016, 10, 12), date(2016, 10, 14)
CITIES = """city,state,latitude,longitude
Quito,Pichincha,-0.2298,-78.525
Ambato,Tungurahua,-1.2491,-78.6168
"""


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, params: dict) -> dict:
        self.calls.append(params)
        span = days(
            date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
        )
        tmax = 20.0 if params["latitude"] == "-0.2298" else 23.0  # tell the cities apart
        return {
            "timezone": TIMEZONE,
            "daily_units": UNITS,
            "daily": {
                "time": [d.isoformat() for d in span],
                "temperature_2m_max": [tmax] * len(span),
                "temperature_2m_min": [8.0] * len(span),
                "precipitation_sum": [1.5] * len(span),
            },
        }


@pytest.fixture
def landed(tmp_path: Path) -> tuple[Path, Path, FakeApi, list[float]]:
    (tmp_path / "cities.csv").write_text(CITIES)
    api, waits = FakeApi(), []
    out, cache = tmp_path / "landing", tmp_path / "cache"
    n = fw.land_weather(
        tmp_path / "cities.csv",
        out,
        cache,
        START,
        END,
        "local-20261013150000",
        api,
        sleep=waits.append,
    )
    assert n == 3
    return tmp_path, out, api, waits


def rows(path: Path) -> list[tuple]:
    sql = f"SELECT * FROM read_parquet('{path}', hive_partitioning = false)"
    return duckdb.sql(sql).fetchall()


def test_one_partition_per_day_with_one_row_per_city(landed) -> None:
    _, out, api, waits = landed
    parts = sorted((out / "raw" / "weather").iterdir())
    assert [p.name for p in parts] == [f"business_date={d}" for d in days(START, END)]
    for part in parts:
        m = read_manifest(part)
        assert (m.source, m.row_count, m.injected) == ("weather", 2, False)
        assert m.sha256 == sha256_file(part / "part-0000.parquet")
    got = rows(parts[0] / "part-0000.parquet")
    assert got == [
        (START, "Ambato", "Tungurahua", 23.0, 8.0, 1.5, False),  # ordered by city
        (START, "Quito", "Pichincha", 20.0, 8.0, 1.5, False),
    ]
    assert len(api.calls) == 2 and waits == [1.0, 1.0]  # one request per city, a pause after each


def test_rerun_uses_the_cache_and_rewrites_the_same_files(landed) -> None:
    tmp_path, out, _, _ = landed
    part = out / "raw" / "weather" / f"business_date={START}"
    before = read_manifest(part).sha256
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == [
        "ambato_2016-10-12_2016-10-14.json",
        "quito_2016-10-12_2016-10-14.json",
    ]
    api, waits = FakeApi(), []
    fw.land_weather(
        tmp_path / "cities.csv",
        out,
        tmp_path / "cache",
        START,
        END,
        "local-20261013160000",
        api,
        sleep=waits.append,
    )
    assert api.calls == [] and waits == []  # no request, so no pause either
    assert read_manifest(part).sha256 == before
    assert not list(out.rglob("*.tmp"))


def test_duplicate_city_names_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "cities.csv").write_text(CITIES + "Quito,Other,-1.0,-78.0\n")
    with pytest.raises(ValueError, match="duplicate city"):
        fw.read_cities(tmp_path / "cities.csv")


def test_a_bad_cached_response_names_the_file_to_delete(tmp_path: Path) -> None:
    (tmp_path / "cities.csv").write_text(CITIES)
    bad = FakeApi()({"start_date": "2016-10-12", "end_date": "2016-10-14", "latitude": "0"})
    bad["timezone"] = "GMT"
    cached = fw.cache_path(tmp_path / "cache", "Quito", START, END)
    cached.parent.mkdir()
    cached.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="quito_2016-10-12_2016-10-14.json; delete it"):
        fw.land_weather(
            tmp_path / "cities.csv",
            tmp_path / "landing",
            tmp_path / "cache",
            START,
            END,
            "local-20261013150000",
            FakeApi(),
            sleep=lambda s: None,
        )
