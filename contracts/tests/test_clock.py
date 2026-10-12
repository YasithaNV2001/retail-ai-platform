"""System design section 5: the worked examples, as tests."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from retail_contracts.clock import (
    BACKFILL_END,
    DATA_END,
    REPLAY_OFFSET_DAYS,
    business_date,
    dates_to_release,
    release_target,
)

COLOMBO = ZoneInfo("Asia/Colombo")


@pytest.mark.parametrize(
    ("real_moment", "expected"),
    [
        # Sat 10 Oct 2026: first day of the replay
        (datetime(2026, 10, 10, 12, 0, tzinfo=UTC), date(2016, 10, 15)),
        # Thu 22 Oct 2026 02:00 Colombo = 20:30 UTC on 21 Oct: nightly run releases Wed 26 Oct
        (datetime(2026, 10, 22, 2, 0, tzinfo=COLOMBO), date(2016, 10, 26)),
        # Thu 22 Oct 2026 15:00 Colombo = 09:30 UTC: a camera event is stamped Thu 27 Oct
        (datetime(2026, 10, 22, 15, 0, tzinfo=COLOMBO), date(2016, 10, 27)),
        # Tue 10 Aug 2027: last day the clock can release
        (datetime(2027, 8, 10, 12, 0, tzinfo=UTC), date(2017, 8, 15)),
    ],
)
def test_worked_examples(real_moment: datetime, expected: date) -> None:
    assert release_target(real_moment) == expected


def test_colombo_night_is_previous_utc_day() -> None:
    nightly = datetime(2026, 10, 22, 2, 0, tzinfo=COLOMBO)
    assert nightly.astimezone(UTC) == datetime(2026, 10, 21, 20, 30, tzinfo=UTC)


def test_offset_is_whole_weeks_so_weekdays_match() -> None:
    assert REPLAY_OFFSET_DAYS % 7 == 0
    for real in (date(2026, 10, 10), date(2026, 10, 22), date(2027, 1, 1)):
        assert business_date(real).weekday() == real.weekday()


def test_clock_stops_at_data_end() -> None:
    assert business_date(date(2027, 8, 11)) == DATA_END
    assert business_date(date(2030, 1, 1)) == DATA_END


def test_first_run_releases_the_whole_backlog() -> None:
    # Before any nightly release, the last released date is the backfill end.
    now = datetime(2026, 10, 12, 20, 30, tzinfo=UTC)  # business date Mon 17 Oct 2016
    assert dates_to_release(BACKFILL_END, now) == [
        date(2016, 10, 15),
        date(2016, 10, 16),
        date(2016, 10, 17),
    ]


def test_missed_night_is_caught_up_in_order() -> None:
    now = datetime(2026, 10, 21, 20, 30, tzinfo=UTC)  # releases Wed 26 Oct 2016
    assert dates_to_release(date(2016, 10, 24), now) == [date(2016, 10, 25), date(2016, 10, 26)]


def test_nothing_to_release_when_up_to_date() -> None:
    now = datetime(2026, 10, 21, 20, 30, tzinfo=UTC)
    assert dates_to_release(date(2016, 10, 26), now) == []


def test_never_releases_before_backfill_end() -> None:
    now = datetime(2026, 10, 10, 20, 30, tzinfo=UTC)  # business date 15 Oct 2016
    assert dates_to_release(date(2016, 1, 1), now) == [date(2016, 10, 15)]
