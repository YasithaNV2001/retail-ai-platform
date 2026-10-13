from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from rap_lakehouse.manifest import (
    LandingManifest,
    local_run_id,
    partition_dir,
    read_manifest,
    write_manifest,
)

GOOD = {
    "source": "sales",
    "business_date": date(2016, 10, 14),
    "row_count": 3,
    "sha256": "a" * 64,
    "run_id": "local-20261013140000",
    "created_ts": datetime(2026, 10, 13, 14, 0, tzinfo=UTC),
    "injected": False,
}


def test_round_trip(tmp_path: Path) -> None:
    write_manifest(tmp_path, LandingManifest(**GOOD))
    assert read_manifest(tmp_path) == LandingManifest(**GOOD)
    assert '"created_ts": "2026-10-13T14:00:00Z"' in (tmp_path / "_manifest.json").read_text()


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("source", "returns"),  # not a §7.1 source
        ("row_count", -1),
        ("sha256", "abc"),
        ("run_id", "manual-1"),  # §6: gh-<id> or local-<yyyymmddHHMMSS>
        ("created_ts", datetime(2026, 10, 13, 14, 0)),  # naive: timestamps are always UTC
    ],
)
def test_rejects_bad_values(field: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        LandingManifest(**(GOOD | {field: bad}))


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        LandingManifest(**(GOOD | {"extra": 1}))


def test_local_run_id_is_utc() -> None:
    colombo = datetime(2026, 10, 13, 19, 30, 5, tzinfo=ZoneInfo("Asia/Colombo"))
    assert local_run_id(colombo) == "local-20261013140005"


def test_partition_dir_layout(tmp_path: Path) -> None:
    assert partition_dir(tmp_path / "raw", "oil", date(2016, 10, 14)) == (
        tmp_path / "raw" / "oil" / "business_date=2016-10-14"
    )
