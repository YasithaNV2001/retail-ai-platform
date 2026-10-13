"""prepare_local on a tiny synthetic world: 4 days around the backfill boundary."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

import prepare_local as pl
from rap_lakehouse.manifest import read_manifest, sha256_file

BACKFILL_END = date(2016, 10, 14)
DATA_END = date(2016, 10, 16)

FILES = {
    "train.csv": """id,date,store_nbr,item_nbr,unit_sales,onpromotion
1,2016-10-13,2,20,3.5,
2,2016-10-13,1,10,1,False
3,2016-10-14,1,10,-2,True
4,2016-10-15,1,10,4,False
5,2016-10-17,1,10,9,False
""",
    "transactions.csv": """date,store_nbr,transactions
2016-10-13,1,100
2016-10-15,1,120
""",
    "oil.csv": """date,dcoilwtico
2016-10-13,50.4
2016-10-14,
""",
    "items.csv": """item_nbr,family,class,perishable
10,BEVERAGES,1010,0
20,DAIRY,2020,1
""",
    "stores.csv": """store_nbr,city,state,type,cluster
1,Quito,Pichincha,A,5
2,Quito,Pichincha,B,6
""",
    "holidays_events.csv": """date,type,locale,locale_name,description,transferred
2016-10-14,Holiday,Local,Quito,Test,False
""",
    "cities.csv": "city,state,latitude,longitude\nQuito,Pichincha,-0.2298,-78.525\n",
}


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "favorita"
    src.mkdir()
    for name, text in FILES.items():
        (src / name).write_text(text)
    out = tmp_path / "rap" / "landing"
    pl.prepare(src, out, src / "cities.csv", "local-20261013140000", BACKFILL_END, DATA_END)
    return src, out


def read_sql(path: Path) -> str:
    # hive_partitioning = false: show the file exactly as written. By default DuckDB would add a
    # business_date column parsed from the business_date=... folder name.
    return f"SELECT * FROM read_parquet('{path}', hive_partitioning = false)"


def rows(path: Path) -> list[tuple]:
    return duckdb.sql(read_sql(path)).fetchall()


def test_backfill_and_vault_split(world: tuple[Path, Path]) -> None:
    _, out = world
    for source in ("sales", "transactions", "oil"):
        raw = sorted(p.name for p in (out / "raw" / source).iterdir())
        vault = sorted(p.name for p in (out / "vault" / source).iterdir())
        assert raw == ["business_date=2016-10-13", "business_date=2016-10-14"]
        assert vault == ["business_date=2016-10-15", "business_date=2016-10-16"]


def test_every_day_has_a_partition_even_when_empty(world: tuple[Path, Path]) -> None:
    _, out = world
    empty = out / "vault" / "sales" / "business_date=2016-10-16"
    assert read_manifest(empty).row_count == 0
    assert rows(empty / "part-0000.parquet") == []


def test_rows_after_data_end_are_not_landed(world: tuple[Path, Path]) -> None:
    _, out = world
    assert not (out / "vault" / "sales" / "business_date=2016-10-17").exists()


def test_manifest_matches_file(world: tuple[Path, Path]) -> None:
    _, out = world
    part = out / "raw" / "sales" / "business_date=2016-10-13"
    m = read_manifest(part)
    assert (m.source, m.business_date, m.injected) == ("sales", date(2016, 10, 13), False)
    assert m.row_count == len(rows(part / "part-0000.parquet")) == 2
    assert m.sha256 == sha256_file(part / "part-0000.parquet")
    assert m.run_id == "local-20261013140000"


def test_types_order_and_injected_flag(world: tuple[Path, Path]) -> None:
    _, out = world
    part = out / "raw" / "sales" / "business_date=2016-10-13" / "part-0000.parquet"
    schema = {r[0]: r[1] for r in duckdb.sql("DESCRIBE " + read_sql(part)).fetchall()}
    assert schema["id"] == "INTEGER" and schema["store_nbr"] == "INTEGER"
    assert schema["unit_sales"] == "DOUBLE"
    assert schema["onpromotion"] == "BOOLEAN" and schema["_injected"] == "BOOLEAN"
    got = rows(part)
    assert [r[2] for r in got] == [1, 2]  # ordered by store_nbr, item_nbr
    assert got[1][5] is None  # empty onpromotion stays NULL, not False
    assert all(r[-1] is False for r in got)


def test_null_oil_price_is_kept(world: tuple[Path, Path]) -> None:
    _, out = world
    got = rows(out / "raw" / "oil" / "business_date=2016-10-14" / "part-0000.parquet")
    assert got == [(date(2016, 10, 14), None, False)]


def test_returns_are_landed_unchanged(world: tuple[Path, Path]) -> None:
    _, out = world
    got = rows(out / "raw" / "sales" / "business_date=2016-10-14" / "part-0000.parquet")
    assert got[0][4] == -2.0  # splitting sold/returned is silver's job, not landing's


def test_static_files(world: tuple[Path, Path]) -> None:
    _, out = world
    for name, n in (("items", 2), ("stores", 2), ("holidays", 1), ("cities", 1)):
        assert len(rows(out / "static" / name / "v1" / f"{name}.parquet")) == n
    items = rows(out / "static" / "items" / "v1" / "items.parquet")
    assert [r[3] for r in items] == [False, True]  # perishable 0/1 becomes a BOOLEAN flag


def test_rerun_is_idempotent(world: tuple[Path, Path]) -> None:
    src, out = world
    part = out / "raw" / "sales" / "business_date=2016-10-13"
    before = read_manifest(part).sha256
    pl.prepare(src, out, src / "cities.csv", "local-20261013150000", BACKFILL_END, DATA_END)
    assert read_manifest(part).sha256 == before
    assert not list(out.rglob("*.tmp"))
    assert not list(out.parent.glob("prepare_local_*"))  # staging DuckDB file cleaned up


def test_missing_input_fails_before_writing(tmp_path: Path) -> None:
    src = tmp_path / "favorita"
    src.mkdir()
    for name, text in FILES.items():
        if name != "oil.csv":
            (src / name).write_text(text)
    out = tmp_path / "rap" / "landing"
    with pytest.raises(FileNotFoundError, match="oil.csv"):
        pl.prepare(src, out, src / "cities.csv", "local-20261013140000", BACKFILL_END, DATA_END)
    assert not out.exists()
