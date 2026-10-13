"""Landing-zone partitions and their manifests (System design §7.1).

Layout: LANDING/{raw,vault}/SOURCE/business_date=YYYY-MM-DD/ holds part-0000.parquet
and _manifest.json.
Bronze refuses a partition whose row count or sha256 disagrees with its manifest (DQ-01).
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Source = Literal["sales", "transactions", "oil", "weather", "master_changes", "footfall"]

PART_FILE = "part-0000.parquet"
MANIFEST_FILE = "_manifest.json"
RUN_ID_PATTERN = r"^(gh-\d+|local-\d{14})$"  # System design §6


class LandingManifest(BaseModel):
    """One _manifest.json: exactly the §7.1 fields, nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Source
    business_date: date
    row_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    created_ts: AwareDatetime
    injected: bool


def local_run_id(now: datetime | None = None) -> str:
    """run_id for runs on the PC: local-<yyyymmddHHMMSS> in UTC (§6)."""
    now = now or datetime.now(UTC)
    return "local-" + now.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def partition_dir(zone_root: Path, source: str, business_date: date) -> Path:
    return zone_root / source / f"business_date={business_date.isoformat()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(part_dir: Path, manifest: LandingManifest) -> None:
    """Write atomically: a reader never sees a half-written manifest."""
    tmp = part_dir / (MANIFEST_FILE + ".tmp")
    tmp.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, part_dir / MANIFEST_FILE)


def read_manifest(part_dir: Path) -> LandingManifest:
    return LandingManifest.model_validate_json((part_dir / MANIFEST_FILE).read_text("utf-8"))
