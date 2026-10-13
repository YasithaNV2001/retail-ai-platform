"""Unit tests for landing/build_reference_data.py on tiny synthetic inputs (no Kaggle rows)."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

import build_reference_data as brd

TRAIN = """id,date,store_nbr,item_nbr,unit_sales,onpromotion
1,2015-10-14,1,10,100,
2,2015-10-15,1,10,5,False
3,2016-10-14,2,20,5,True
4,2016-10-15,1,30,999,
5,2016-01-01,1,30,-50,
6,2016-01-01,2,30,1.5,False
7,2016-01-02,1,40,5,False
"""
ITEMS = """item_nbr,family,class,perishable
10,BEVERAGES,1010,0
20,DAIRY,2020,1
30,GROCERY I,3030,0
40,BEVERAGES,1011,0
"""


@pytest.fixture
def csvs(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "train.csv").write_text(TRAIN)
    (tmp_path / "items.csv").write_text(ITEMS)
    return tmp_path / "train.csv", tmp_path / "items.csv"


def test_top_items_window_returns_and_ties(csvs: tuple[Path, Path]) -> None:
    train, items = csvs
    got = brd.top_items(
        duckdb.connect(), train, items, date(2015, 10, 15), date(2016, 10, 14), n=10
    )
    # Day before and day after the window are excluded (items 10's 100 and 30's 999).
    # Returns don't count: item 30 = max(-50, 0) + 1.5 = 1.5.
    # Items 10, 20 and 40 tie on 5 units: lowest item_nbr ranks first.
    assert got == [
        (10, "BEVERAGES", 1),
        (20, "DAIRY", 2),
        (40, "BEVERAGES", 3),
        (30, "GROCERY I", 4),
    ]


def test_top_items_limits_to_n(csvs: tuple[Path, Path]) -> None:
    train, items = csvs
    got = brd.top_items(duckdb.connect(), train, items, date(2015, 10, 15), date(2016, 10, 14), n=2)
    assert [r[2] for r in got] == [1, 2]


def result(name: str, admin1: str, pop: int = 1000, code: str = "PPL", cc: str = "EC") -> dict:
    return {
        "id": 1,
        "name": name,
        "admin1": admin1,
        "population": pop,
        "feature_code": code,
        "country_code": cc,
        "latitude": -1.0,
        "longitude": -78.0,
    }


def test_geocode_matches_province_ignoring_accents() -> None:
    results = [
        result("Santo Domingo", "Pichincha", pop=50),
        result("Santo Domingo de los Colorados", "Santo Domingo de los Tsáchilas", pop=300_000),
    ]
    hit = brd.pick_geocode_result("Santo Domingo", "Santo Domingo de los Tsachilas", results)
    assert hit["admin1"] == "Santo Domingo de los Tsáchilas"


def test_geocode_accepts_spanish_province_prefix() -> None:
    # Real response seen on 2026-10-13: admin1 comes back as "Provincia de Tungurahua".
    results = [
        result("Ambato", "Provincia de Tungurahua", pop=150_000),
        result("Ambato Loma", "Pichincha", pop=100),
    ]
    assert brd.pick_geocode_result("Ambato", "Tungurahua", results)["name"] == "Ambato"
    assert brd.province_key("Provincia del Guayas") == "guayas"
    assert brd.province_key("Provincia de Los Ríos") == "los rios"


def test_geocode_prefers_most_populous_match() -> None:
    results = [result("Quito", "Pichincha", pop=10), result("Quito", "Pichincha", pop=1_600_000)]
    assert brd.pick_geocode_result("Quito", "Pichincha", results)["population"] == 1_600_000


def test_geocode_ignores_non_places_and_other_countries() -> None:
    results = [result("Loja", "Loja", code="ADM2"), result("Loja", "Loja", cc="ES")]
    with pytest.raises(LookupError, match="candidates"):
        brd.pick_geocode_result("Loja", "Loja", results)


def test_bounds_check_rejects_points_outside_ecuador() -> None:
    brd.check_bounds([{"city": "Quito", "latitude": -0.22, "longitude": -78.51}])
    with pytest.raises(ValueError, match="outside"):
        brd.check_bounds([{"city": "Galapagos", "latitude": -0.9, "longitude": -90.9}])


FAMILIES = {"BEVERAGES": False, "DAIRY": True, "GROCERY I": False, "PRODUCE": True}


def test_supplier_terms_rules() -> None:
    rows = brd.supplier_terms(FAMILIES)
    assert [r.family for r in rows] == sorted(FAMILIES)
    assert len({r.supplier_id for r in rows}) == len(rows)
    for r in rows:
        assert r.moq_units % r.case_size == 0
        days = r.order_days.split("|")
        assert set(days) <= set(brd.WEEKDAYS)
        if FAMILIES[r.family]:
            assert (r.lead_time_days, len(days)) == (1, 6)
            assert r.shelf_life_days is not None and r.shelf_life_days > 0
        else:
            assert 2 <= r.lead_time_days <= 4 and len(days) == 2
            assert r.shelf_life_days is None


def test_supplier_terms_are_deterministic() -> None:
    assert brd.supplier_terms(FAMILIES) == brd.supplier_terms(FAMILIES)


def test_injection_moves_store_to_another_cluster_in_its_city() -> None:
    stores = [
        {"store_nbr": "44", "city": "Quito", "cluster": "5"},
        {"store_nbr": "45", "city": "Quito", "cluster": "11"},
        {"store_nbr": "46", "city": "Quito", "cluster": "8"},
        {"store_nbr": "24", "city": "Guayaquil", "cluster": "1"},
    ]
    assert brd.injection_target_cluster(stores) == (5, 8)


def test_injection_fails_when_city_has_one_cluster() -> None:
    stores = [{"store_nbr": "44", "city": "Quito", "cluster": "5"}]
    with pytest.raises(ValueError, match="no other cluster"):
        brd.injection_target_cluster(stores)
