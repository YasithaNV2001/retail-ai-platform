from datetime import date

import pyarrow as pa
import pytest

from rap_lakehouse.partitions import days
from rap_lakehouse.weather import (
    RATE_LIMIT_WAIT_S,
    TIMEZONE,
    UNITS,
    archive_params,
    fetch_archive,
    parse_daily,
    to_table,
)

START, END = date(2016, 10, 12), date(2016, 10, 14)


def payload(start: date = START, end: date = END, **overrides: object) -> dict:
    n = len(days(start, end))
    body = {
        "timezone": TIMEZONE,
        "daily_units": {"time": "iso8601"} | UNITS,
        "daily": {
            "time": [d.isoformat() for d in days(start, end)],
            "temperature_2m_max": [20.5] * n,
            "temperature_2m_min": [9.0] * n,
            "precipitation_sum": [0] * (n - 1) + [None],  # ints and nulls both occur in JSON
        },
    }
    return body | overrides


class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code, self.body, self.text = status_code, body or {}, str(body)

    def json(self) -> dict:
        return self.body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses, self.calls = list(responses), 0

    def get(self, url: str, params: dict, timeout: int) -> FakeResponse:
        self.calls += 1
        return self.responses.pop(0)


def test_archive_params_match_the_spec() -> None:
    params = archive_params(-0.2298, -78.525, date(2013, 1, 1), date(2016, 10, 14))
    assert params == {
        "latitude": "-0.2298",
        "longitude": "-78.525",
        "start_date": "2013-01-01",
        "end_date": "2016-10-14",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "America/Guayaquil",
    }


def test_parse_daily_one_row_per_day() -> None:
    rows = parse_daily(payload(), "Quito", "Pichincha", START, END)
    assert [r["date"] for r in rows] == days(START, END)
    assert rows[0] == {
        "date": START,
        "city": "Quito",
        "state": "Pichincha",
        "temperature_2m_max": 20.5,
        "temperature_2m_min": 9.0,
        "precipitation_sum": 0,
    }
    assert rows[-1]["precipitation_sum"] is None  # a gap stays null; silver decides (DQ-06)


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (payload(timezone="GMT"), "timezone"),
        (payload(daily_units={"temperature_2m_max": "°F"}), "temperature_2m_max"),
        (payload(end=date(2016, 10, 13)), "expected every day"),
    ],
)
def test_parse_daily_rejects_what_was_not_asked_for(bad: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_daily(bad, "Quito", "Pichincha", START, END)


def test_to_table_types() -> None:
    table = to_table(parse_daily(payload(), "Quito", "Pichincha", START, END))
    assert table.schema.field("date").type == pa.date32()
    assert table.schema.field("precipitation_sum").type == pa.float64()  # JSON 0 becomes 0.0
    assert table.column("precipitation_sum").null_count == 1


def test_fetch_waits_out_the_rate_limit() -> None:
    session = FakeSession(FakeResponse(429), FakeResponse(200, payload()))
    waits: list[float] = []
    assert fetch_archive(session, {}, sleep=waits.append) == payload()
    assert waits == [RATE_LIMIT_WAIT_S] and session.calls == 2


def test_fetch_gives_up_after_repeated_rate_limits() -> None:
    session = FakeSession(*[FakeResponse(429) for _ in range(6)])
    waits: list[float] = []
    with pytest.raises(RuntimeError, match="rate-limiting"):
        fetch_archive(session, {}, sleep=waits.append)
    assert len(waits) == 5 and session.calls == 6


def test_fetch_reports_the_api_reason_on_400() -> None:
    session = FakeSession(FakeResponse(400, {"error": True, "reason": "bad daily variable"}))
    with pytest.raises(ValueError, match="bad daily variable"):
        fetch_archive(session, {}, sleep=lambda s: None)
