from datetime import date, datetime, timedelta, timezone

REPLAY_OFFSET_DAYS = 3647  # 521 weeks, so weekdays match
BACKFILL_END = date(2016, 10, 14)  # last day loaded by the one-off backfill
DATA_END = date(2017, 8, 15)  # last day in train.csv


def business_date(real_utc_date: date) -> date:
    return min(real_utc_date - timedelta(days=REPLAY_OFFSET_DAYS), DATA_END)


def release_target(now_utc: datetime) -> date:
    """Latest business date the nightly run may release at this moment."""
    return business_date(now_utc.astimezone(timezone.utc).date())


def dates_to_release(last_released: date, now_utc: datetime) -> list[date]:
    start = max(last_released, BACKFILL_END) + timedelta(days=1)
    end = release_target(now_utc)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
