"""P1 step 1.2: build the shared reference files in contracts/ from the raw Favorita CSVs.

Writes (System design §8.4):
  contracts/config/cities.csv               city, state, latitude, longitude (22 cities)
  contracts/data/demo_items.csv             item_nbr, family, rank (top 500, frozen after creation)
  contracts/data/supplier_terms.csv         one fictional supplier per family (33 rows)
  contracts/config/replay_injections.yaml   created once: store 44 changes cluster on 2016-11-15

thresholds.yaml is hand-written, not generated. Run from p1-lakehouse/:
  uv run python landing/build_reference_data.py
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
import time
import unicodedata
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path

import duckdb
import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("build_reference_data")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "contracts" / "config"
DATA_DIR = REPO_ROOT / "contracts" / "data"

DEMO_WINDOW_START = date(2015, 10, 15)  # 365 days before the replay starts (§7.2, step 1.2)
DEMO_WINDOW_END = date(2016, 10, 14)  # = BACKFILL_END
DEMO_ITEMS_N = 500  # ADR-009 demo scope

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
# City names that Open-Meteo's geocoder spells or files differently from stores.csv.
# Add an entry only with evidence. Format: {"<city in stores.csv>": ("<search>", "<admin1>")}
# Libertad: holidays_events.csv has "Cantonizacion de Libertad", so it is the canton town
# La Libertad (pop 75,881). The geocoder's own "Libertad, Guayas" is a PPLX (a neighbourhood).
GEOCODE_OVERRIDES: dict[str, tuple[str, str]] = {"Libertad": ("La Libertad", "Guayas")}

INJECTION_STORE = 44
INJECTION_DATE = date(2016, 11, 15)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SEED = 7


# ---------- pure functions (unit-tested) ----------


def normalise(text: str) -> str:
    """Lower-case, strip accents and spaces at the ends: 'Tsáchilas ' -> 'tsachilas'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip().lower()


def province_key(admin1: str) -> str:
    """Comparable province: geocoder 'Provincia de Tungurahua' vs stores.csv 'Tungurahua'."""
    key = normalise(admin1)
    for prefix in ("provincia del ", "provincia de "):
        if key.startswith(prefix):
            return key.removeprefix(prefix)
    return key


def pick_geocode_result(city: str, state: str, results: list[dict]) -> dict:
    """Choose the populated place in Ecuador whose province (admin1) matches the store's state."""
    wanted_admin1 = GEOCODE_OVERRIDES.get(city, (city, state))[1]
    places = [
        r
        for r in results
        if r.get("country_code") == "EC" and str(r.get("feature_code", "")).startswith("PPL")
    ]
    matches = [
        r for r in places if province_key(r.get("admin1", "")) == province_key(wanted_admin1)
    ]
    if not matches:
        seen = [
            (r.get("name"), r.get("admin1"), r.get("latitude"), r.get("longitude")) for r in results
        ]
        raise LookupError(
            f"no geocoder match for city={city!r} state={state!r}; candidates={seen}. "
            "Check them and add an entry to GEOCODE_OVERRIDES."
        )
    # The API returns results by relevance; prefer the most populous match when several remain.
    return max(matches, key=lambda r: r.get("population") or 0)


def top_items_sql() -> str:
    """Top items by units sold (returns excluded) in the window; ties broken by item_nbr."""
    return """
        WITH sold AS (
            SELECT item_nbr, SUM(GREATEST(unit_sales, 0)) AS units_sold
            FROM read_csv(
                $train, header = true,
                columns = {'id': 'BIGINT', 'date': 'DATE', 'store_nbr': 'INTEGER',
                           'item_nbr': 'INTEGER', 'unit_sales': 'DOUBLE', 'onpromotion': 'VARCHAR'}
            )
            WHERE date BETWEEN $start AND $end
            GROUP BY item_nbr
        )
        SELECT s.item_nbr, i.family,
               ROW_NUMBER() OVER (ORDER BY s.units_sold DESC, s.item_nbr) AS rank
        FROM sold s
        JOIN read_csv(
            $items, header = true,
            columns = {'item_nbr': 'INTEGER', 'family': 'VARCHAR', 'class': 'INTEGER',
                       'perishable': 'INTEGER'}
        ) i USING (item_nbr)
        QUALIFY rank <= $n
        ORDER BY rank
    """


def top_items(
    con: duckdb.DuckDBPyConnection,
    train_csv: Path,
    items_csv: Path,
    start: date = DEMO_WINDOW_START,
    end: date = DEMO_WINDOW_END,
    n: int = DEMO_ITEMS_N,
) -> list[tuple[int, str, int]]:
    params = {"train": str(train_csv), "items": str(items_csv), "start": start, "end": end, "n": n}
    return [(int(a), str(b), int(c)) for a, b, c in con.execute(top_items_sql(), params).fetchall()]


@dataclass(frozen=True)
class SupplierTerms:
    family: str
    supplier_id: str
    supplier_name: str
    lead_time_days: int
    moq_units: int
    case_size: int
    order_days: str  # weekday abbreviations joined by "|", for example "Mon|Thu"
    shelf_life_days: int | None  # perishable families only


def supplier_terms(families: dict[str, bool], seed: int = SEED) -> list[SupplierTerms]:
    """One fictional supplier per family. families maps family -> is_perishable."""
    rng = random.Random(seed)
    rows = []
    for idx, family in enumerate(sorted(families), start=1):
        perishable = families[family]
        case_size = rng.choice([6, 12, 24])
        if perishable:
            lead_time, order_days, shelf_life = 1, WEEKDAYS[:6], rng.randint(3, 14)
        else:
            lead_time = rng.randint(2, 4)
            order_days = tuple(sorted(rng.sample(WEEKDAYS[:6], 2), key=WEEKDAYS.index))
            shelf_life = None
        rows.append(
            SupplierTerms(
                family=family,
                supplier_id=f"SUP-{idx:03d}",
                supplier_name=f"Andes {family.title()} Supply (fictional)",
                lead_time_days=lead_time,
                moq_units=case_size * rng.randint(2, 8),
                case_size=case_size,
                order_days="|".join(order_days),
                shelf_life_days=shelf_life,
            )
        )
    return rows


def injection_target_cluster(
    stores: list[dict], store_nbr: int = INJECTION_STORE
) -> tuple[int, int]:
    """(from_cluster, to_cluster): move the store to the lowest other cluster used in its city."""
    store = next(s for s in stores if int(s["store_nbr"]) == store_nbr)
    current = int(store["cluster"])
    same_city = {int(s["cluster"]) for s in stores if s["city"] == store["city"]} - {current}
    if not same_city:
        raise ValueError(f"store {store_nbr}: no other cluster in {store['city']}")
    return current, min(same_city)


# ---------- I/O ----------


def http_session() -> requests.Session:
    retry = Retry(total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def geocode_cities(pairs: list[tuple[str, str]], pause_s: float = 1.0) -> list[dict]:
    session = http_session()
    rows = []
    for city, state in pairs:
        query = GEOCODE_OVERRIDES.get(city, (city, state))[0]
        params = {
            "name": query,
            "count": 20,
            "countryCode": "EC",
            "language": "es",
            "format": "json",
        }
        resp = session.get(GEOCODING_URL, params=params, timeout=30)
        resp.raise_for_status()
        hit = pick_geocode_result(city, state, resp.json().get("results", []))
        rows.append(
            {
                "city": city,
                "state": state,
                "latitude": round(float(hit["latitude"]), 4),
                "longitude": round(float(hit["longitude"]), 4),
            }
        )
        log.info(
            "geocoded %s, %s -> %s, %s (%s)", city, state, hit["name"], hit["admin1"], hit["id"]
        )
        time.sleep(pause_s)
    return rows


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    log.info("wrote %s (%d rows)", path.relative_to(REPO_ROOT), len(rows))


def check_bounds(cities: list[dict]) -> None:
    """Step 1.2 check: every city lies inside mainland Ecuador's box."""
    for c in cities:
        if not (-5 <= c["latitude"] <= 2 and -81 <= c["longitude"] <= -75):
            raise ValueError(f"{c['city']} geocoded outside Ecuador's box: {c}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--favorita-dir", type=Path, default=Path.home() / "data" / "favorita")
    args = parser.parse_args()
    src = args.favorita_dir.expanduser()
    for name in ("train.csv", "items.csv", "stores.csv"):
        if not (src / name).is_file():
            raise FileNotFoundError(f"missing {src / name}; pass --favorita-dir")

    stores = read_csv_rows(src / "stores.csv")
    items = read_csv_rows(src / "items.csv")

    # cities.csv
    pairs = sorted({(s["city"], s["state"]) for s in stores})
    cities = geocode_cities(pairs)
    check_bounds(cities)
    write_csv(CONFIG_DIR / "cities.csv", ["city", "state", "latitude", "longitude"], cities)

    # demo_items.csv
    con = duckdb.connect()
    con.execute("SET memory_limit = '4GB'")  # WSL has 10 GB; leave room for the rest
    con.execute("SET threads = 4")
    started = time.monotonic()
    demo = top_items(con, src / "train.csv", src / "items.csv")
    log.info("ranked demo items in %.0f s", time.monotonic() - started)
    write_csv(
        DATA_DIR / "demo_items.csv",
        ["item_nbr", "family", "rank"],
        [{"item_nbr": i, "family": f, "rank": r} for i, f, r in demo],
    )

    # supplier_terms.csv: a family is perishable when most of its items are
    counts: dict[str, list[int]] = {}
    for it in items:
        counts.setdefault(it["family"], []).append(int(it["perishable"]))
    families = {fam: sum(flags) * 2 > len(flags) for fam, flags in counts.items()}
    log.info("perishable families: %s", sorted(f for f, p in families.items() if p))
    terms = supplier_terms(families)
    write_csv(
        DATA_DIR / "supplier_terms.csv",
        [f.name for f in fields(SupplierTerms)],
        [asdict(t) | {"shelf_life_days": t.shelf_life_days or ""} for t in terms],
    )

    # replay_injections.yaml: create once; injections are append-only after that (§5)
    inj_path = CONFIG_DIR / "replay_injections.yaml"
    if inj_path.exists():
        log.info("kept existing %s (append-only)", inj_path.relative_to(REPO_ROOT))
    else:
        from_cluster, to_cluster = injection_target_cluster(stores)
        doc = {
            "injections": [
                {
                    "id": "INJ-001",
                    "owner": "P1",
                    "business_date": INJECTION_DATE.isoformat(),
                    "kind": "master_change",
                    "entity": "store",
                    "key": {"store_nbr": INJECTION_STORE},
                    "changes": {"cluster": {"from": from_cluster, "to": to_cluster}},
                    "reason": "Exercise SCD Type 2 in dim_store (System design §5)",
                }
            ]
        }
        inj_path.write_text(
            "# Deliberate, flagged data changes applied by the release step (System design §5).\n"
            "# Append-only: never edit or remove an entry once its business_date is released.\n"
            + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        log.info(
            "wrote %s: store %d cluster %d -> %d",
            inj_path.relative_to(REPO_ROOT),
            INJECTION_STORE,
            from_cluster,
            to_cluster,
        )

    log.info("checks: %d cities, %d demo items, %d suppliers", len(cities), len(demo), len(terms))
    if (len(cities), len(demo), len(terms)) != (22, 500, 33):
        raise SystemExit("counts differ from the spec (22, 500, 33): stop and investigate")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
