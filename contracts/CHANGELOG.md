# Changelog

## 0.2.0 (2026-10-13)
- Shared reference files (System design §8.4): `config/cities.csv`, `config/thresholds.yaml`,
  `config/replay_injections.yaml` (INJ-001: store 44 moves from cluster 5 to 6 on 2016-11-15),
  `data/demo_items.csv` (top 500, frozen), `data/supplier_terms.csv` (33 fictional suppliers).

## 0.1.0 (2026-10-12)
- Replay clock (`clock.py`), System design §5 verbatim, with the worked examples as tests.
- `settings.py`: `RAP_ENV`, `RAP_CATALOG`, `RAP_SCHEMA_PREFIX` and `table(layer, name)`.
